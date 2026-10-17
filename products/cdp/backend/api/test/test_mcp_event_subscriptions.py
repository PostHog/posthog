import json
import base64
from datetime import timedelta
from typing import TYPE_CHECKING

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.utils import timezone

from parameterized import parameterized
from pydantic import JsonValue

from posthog.schema import HogQLQueryResponse

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models.file_system.file_system import FileSystem
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey, PropertyDefinition, Team

from products.access_control.backend.models.access_control import AccessControl
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.actions.backend.models.action import Action
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription


class MCPEventSubscriptionTestCase(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag = patch(
            "products.cdp.backend.presentation.mcp_event_subscriptions.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.flag_mock = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.callback = patch("products.cdp.backend.mcp_events.verify_callback")
        self.callback.start()
        self.addCleanup(self.callback.stop)
        self.key = self.create_personal_api_key_with_scopes(["mcp_event_subscription:write", "query:read"])
        self.client.logout()
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {self.key}"}
        self.url = f"/api/projects/{self.team.pk}/mcp_event_subscriptions/"
        self.callback_url = "https://example.com/callback"
        self.secret = "whsec_" + base64.b64encode(b"a" * 32).decode()
        self.payload: dict[str, object] = {
            "name": "posthog.event_captured",
            "arguments": {
                "project_id": self.team.pk,
                "filters": {"events": [{"id": "example_event", "type": "events"}]},
            },
            "delivery": {"mode": "webhook", "url": "https://example.com/callback", "secret": self.secret},
        }

    def subscribe(self) -> MCPEventSubscription:
        response = self.client.post(
            self.url + "subscribe/", self.payload, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertTrue(
            any(call.args[:2] == ("mcp-events", self.user.distinct_id) for call in self.flag_mock.call_args_list)
        )
        self.assertNotIn(self.secret, json.dumps(response.json()))
        return MCPEventSubscription.objects.for_team(self.team.pk).get(id=response.json()["id"])

    def authorize(
        self,
        subscription: MCPEventSubscription,
        generation: object | None = None,
        filter_bytecode: list[JsonValue] | None = None,
        properties: dict[str, JsonValue] | None = None,
    ) -> "_MonkeyPatchedResponse":
        body = {
            "eventId": "a5524ac5-d7c5-43b6-862c-f5971da694c8",
            "name": "posthog.event_captured",
            "timestamp": timezone.now().isoformat(),
            "data": {
                "event": "example_event",
                "distinct_id": "sample-user",
                "properties": properties if properties is not None else {"plan": "enterprise"},
            },
            "cursor": None,
        }
        assert subscription.hog_function is not None
        assert subscription.hog_function.filters is not None
        return self.client.post(
            self.url + str(subscription.pk) + "/authorize_delivery/",
            {
                "generation": str(generation or subscription.generation),
                "function_id": str(subscription.hog_function_id),
                "filter_bytecode": filter_bytecode
                if filter_bytecode is not None
                else subscription.hog_function.filters["bytecode"],
                "url": self.callback_url,
                "body": json.dumps(body),
            },
            HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"],
        )


class TestMCPEventSubscriptionAPI(MCPEventSubscriptionTestCase):
    def test_subscription_cannot_be_accessed_by_another_owner(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        other_user = self._create_user("other@example.com")
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(self.url + str(subscription.pk) + "/").status_code, 404)

    @parameterized.expand(["destination", "file_system"])
    def test_generic_destination_api_cannot_modify_subscription(self, surface: str) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        function = subscription.hog_function
        if surface == "destination":
            key = self.create_personal_api_key_with_scopes(["hog_function:write"])
            response = self.client.patch(
                f"/api/projects/{self.team.pk}/hog_functions/{function.pk}/",
                {"enabled": False},
                HTTP_AUTHORIZATION=f"Bearer {key}",
            )
            self.assertEqual(response.status_code, 403, response.json())
        else:
            self.assertFalse(FileSystem.objects.filter(team=self.team, ref=str(function.pk)).exists())
            self.assertFalse(HogFunction.get_file_system_unfiled(self.team).filter(pk=function.pk).exists())
            entry = FileSystem.objects.create(
                team=self.team,
                path="Example managed destination",
                type="hog_function/destination",
                ref=str(function.pk),
                created_by=self.user,
            )
            self.client.force_login(self.user)
            response = self.client.delete(f"/api/projects/{self.team.pk}/file_system/{entry.pk}/")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertFalse(FileSystem.objects.filter(pk=entry.pk).exists())
        function.refresh_from_db()
        subscription.refresh_from_db()
        self.assertTrue(subscription.active)
        self.assertTrue(function.enabled)
        self.assertFalse(function.deleted)

    @parameterized.expand(["query_scope", "credential", "membership"])
    def test_revocation_stops_queued_delivery(self, revoked: str) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        if revoked == "query_scope":
            PersonalAPIKey.objects.filter(user=self.user).update(scopes=["mcp_event_subscription:write"])
        elif revoked == "credential":
            PersonalAPIKey.objects.filter(user=self.user).delete()
        else:
            self.organization_membership.delete()
        response = self.authorize(subscription)
        self.assertIn(response.status_code, [401, 403])

    def test_same_user_cannot_deliver_using_another_credential(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        key = self.create_personal_api_key_with_scopes(["mcp_event_subscription:write", "query:read"])
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {key}"}
        self.assertEqual(self.authorize(subscription).status_code, 403)

    @parameterized.expand(
        [
            ("preview", "unsupported_global = 'value'", "Real-time filters cannot read"),
            ("subscribe", "unsupported_global = 'value'", "Real-time filters cannot read"),
            ("preview", "typeof(properties.rating) = 'integer'", "This filter cannot be previewed"),
            ("subscribe", "typeof(properties.rating) = 'integer'", "This filter cannot be previewed"),
        ]
    )
    def test_invalid_realtime_filters_cannot_preview_or_subscribe(
        self, endpoint: str, expression: str, message: str
    ) -> None:
        arguments = {
            "project_id": self.team.pk,
            "filters": {"properties": [{"type": "hogql", "key": expression}]},
        }
        payload = arguments if endpoint == "preview" else {**self.payload, "arguments": arguments}
        response = self.client.post(
            self.url + endpoint + "/", payload, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]
        )
        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn(message, json.dumps(response.json()))
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
        self.assertFalse(HogFunction.objects.filter(team=self.team).exists())

    @parameterized.expand(
        [
            (endpoint, location)
            for endpoint in ("preview", "subscribe", "delivery")
            for location in ("actions", "events")
        ]
    )
    @patch(
        "products.access_control.backend.facade.user_access_control.UserAccessControl.access_controls_supported", True
    )
    def test_action_access_is_required_at_setup_and_delivery(self, endpoint: str, location: str) -> None:
        action = Action.objects.create(
            team=self.team, name="Example action", steps_json=[{"event": "example_event"}], created_by=self.user
        )
        self.user = self._create_user("subscriber@example.com")
        self.key = self.create_personal_api_key_with_scopes(["mcp_event_subscription:write", "query:read"])
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {self.key}"}
        arguments = {
            "project_id": self.team.pk,
            "filters": {location: [{"id": str(action.pk), "type": "actions"}]},
        }
        self.payload["arguments"] = arguments
        subscription = self.subscribe() if endpoint == "delivery" else None
        AccessControl.objects.create(team=self.team, resource="action", resource_id=str(action.pk), access_level="none")
        if subscription is not None:
            response = self.authorize(subscription)
        else:
            payload = arguments if endpoint == "preview" else self.payload
            response = self.client.post(
                self.url + endpoint + "/", payload, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]
            )
            self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
            self.assertFalse(HogFunction.objects.filter(team=self.team).exists())
        self.assertEqual(response.status_code, 400, response.json())
        self.assertIn("viewer access", json.dumps(response.json()))

    def test_subscriptions_remain_isolated_between_child_environments(self) -> None:
        parent = self.team
        children = [
            Team.objects.create(organization=self.organization, project=parent.project, parent_team=parent, name=name)
            for name in ("Staging", "Preview")
        ]
        subscriptions = []
        for child in children:
            self.team = child
            self.url = f"/api/projects/{child.pk}/mcp_event_subscriptions/"
            self.payload["arguments"] = {
                "project_id": child.pk,
                "filters": {"events": [{"id": "example_event", "type": "events"}]},
            }
            subscription = self.subscribe()
            self.assertEqual(subscription.team_id, child.pk)
            assert subscription.hog_function is not None
            self.assertEqual(subscription.hog_function.team_id, child.pk)
            subscriptions.append(subscription)
        PersonalAPIKey.objects.filter(user=self.user).update(scoped_teams=[children[-1].pk])
        page = self.client.get(self.url, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"])
        self.assertEqual(page.status_code, 200, page.json())
        self.assertEqual(page.json()["count"], 1)
        self.assertEqual([row["id"] for row in page.json()["results"]], [str(subscriptions[-1].pk)])
        sibling = self.client.get(
            self.url + str(subscriptions[0].pk) + "/", HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]
        )
        self.assertEqual(sibling.status_code, 404, sibling.json())
        authorized = self.authorize(subscriptions[-1])
        self.assertEqual(authorized.status_code, 200, authorized.json())

    def test_delivery_does_not_consume_the_client_api_throttle(self) -> None:
        subscription = self.subscribe()
        with (
            patch("posthog.rate_limit.BurstRateThrottle.allow_request", return_value=False),
            patch("posthog.rate_limit.BurstRateThrottle.wait", return_value=60),
        ):
            self.assertEqual(
                self.client.get(self.url, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]).status_code, 429
            )
            response = self.authorize(subscription)
        self.assertEqual(response.status_code, 200, response.json())

    def test_delivery_rejects_a_different_compiled_filter(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        assert subscription.hog_function.filters is not None
        subscription.hog_function.filters["bytecode"] = ["_H", 1, 31, 1]
        self.assertEqual(self.authorize(subscription).status_code, 403)

    @parameterized.expand(["$active_feature_flags", "$feature_flags"])
    def test_filter_cannot_read_a_restricted_flag_through_an_alias(self, alias: str) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="$feature/secret", property_type="Boolean", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")
        self.payload["arguments"] = {
            "project_id": self.team.pk,
            "filters": {"properties": [{"key": alias, "type": "event", "operator": "is_set"}]},
        }
        response = self.client.post(
            self.url + "subscribe/", self.payload, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]
        )
        self.assertEqual(response.status_code, 403, response.json())

    def test_list_pages_keep_all_subscriptions_with_tied_creation_times(self) -> None:
        first = self.subscribe()
        self.payload["arguments"] = {
            "project_id": self.team.pk,
            "filters": {"events": [{"id": "second_event", "type": "events"}]},
        }
        second = self.subscribe()
        MCPEventSubscription.objects.for_team(self.team.pk).filter(id__in=[first.pk, second.pk]).update(
            created_at=timezone.now()
        )
        response = self.client.get(self.url + "?limit=1", HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"])
        self.assertEqual(response.status_code, 200, response.json())
        page = response.json()
        self.assertEqual(page["count"], 2)
        self.assertIsNotNone(page["next"])
        next_page = self.client.get(page["next"], HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"])
        self.assertEqual(next_page.status_code, 200, next_page.json())
        rows = page["results"] + next_page.json()["results"]
        self.assertEqual([row["id"] for row in rows], sorted([str(first.pk), str(second.pk)], reverse=True))
        self.assertIsNone(next_page.json()["next"])

    @parameterized.expand(["personal_api_key", "oauth"])
    def test_delegated_credentials_cannot_create_long_lived_subscriptions(self, source: str) -> None:
        claims: dict[str, str | int] = {"id": self.user.pk}
        if source == "personal_api_key":
            claims["personal_api_key_id"] = PersonalAPIKey.objects.get(user=self.user).pk
        else:
            application = OAuthApplication.objects.create(
                name="MCP delegated credential test",
                client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
                authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
                redirect_uris="https://example.com/callback",
                algorithm="RS256",
                organization=self.organization,
                user=self.user,
            )
            token = OAuthAccessToken.objects.create(
                user=self.user,
                application=application,
                token="pha_mcp_delegated_test",
                scope="mcp_event_subscription:write query:read",
                expires=timezone.now() + timedelta(hours=1),
                scoped_teams=[self.team.pk],
            )
            claims["oauth_access_token_id"] = str(token.pk)
        credential = encode_jwt(claims, timedelta(minutes=5), PosthogJwtAudience.DELEGATED_USER)
        response = self.client.post(self.url + "subscribe/", self.payload, HTTP_AUTHORIZATION=f"Bearer {credential}")
        self.assertEqual(response.status_code, 403, response.json())
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
        self.assertFalse(HogFunction.objects.filter(team=self.team).exists())

    def test_oauth_refresh_keeps_identity_and_bounds_lifetime_by_token_expiry(self) -> None:
        application = OAuthApplication.objects.create(
            name="MCP events test",
            client_id="mcp-events-test",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            algorithm="RS256",
            organization=self.organization,
            user=self.user,
        )
        expiry = timezone.now() + timedelta(hours=1)
        token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_mcp_events_test",
            scope="mcp_event_subscription:write query:read",
            expires=expiry,
            scoped_teams=[self.team.pk],
        )
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {token.token}"}
        first = self.subscribe()
        self.assertEqual(first.expires_at, expiry)
        refreshed_token = OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token="pha_mcp_events_refreshed_test",
            scope=token.scope,
            expires=expiry + timedelta(hours=1),
            scoped_teams=[self.team.pk],
        )
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {refreshed_token.token}"}
        refreshed = self.subscribe()
        self.assertEqual(first.pk, refreshed.pk)
        self.assertEqual(first.generation, refreshed.generation)
        self.assertEqual(first.hog_function_id, refreshed.hog_function_id)
        self.assertEqual(refreshed.expires_at, refreshed_token.expires)


class TestMCPEventPreviewAPI(MCPEventSubscriptionTestCase):
    def test_query_only_key_can_preview_without_creating_subscription(self) -> None:
        key = self.create_personal_api_key_with_scopes(["query:read"])
        with patch(
            "posthog.hogql_queries.hogql_query_runner.HogQLQueryRunner.run",
            return_value=HogQLQueryResponse(results=[]),
        ):
            response = self.client.post(
                self.url + "preview/",
                {
                    "project_id": self.team.pk,
                    "filters": {"events": [{"id": "example_event", "type": "events"}]},
                },
                HTTP_AUTHORIZATION=f"Bearer {key}",
            )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["examples"], [])
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())

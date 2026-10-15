import json
import base64
from copy import deepcopy
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from parameterized import parameterized
from pydantic import JsonValue
from rest_framework.exceptions import ValidationError

from posthog.models.event.util import create_event
from posthog.models.oauth import OAuthAccessToken, OAuthApplication

if TYPE_CHECKING:
    from rest_framework.response import _MonkeyPatchedResponse

from posthog.clickhouse.query_tagging import tags_context
from posthog.constants import AvailableFeature
from posthog.models import PersonalAPIKey, PropertyDefinition, Team

from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.actions.backend.models.action import Action
from products.cdp.backend.mcp_event_delivery import MCPCallbackError, signing_key, verify_callback
from products.cdp.backend.mcp_event_properties import MCPEventPropertyAccess
from products.cdp.backend.mcp_events import MCPEventSubscriptions
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import HogFunction
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription
from products.cdp.backend.tasks.hog_functions import refresh_affected_hog_functions


class TestMCPEventSigning(SimpleTestCase):
    @parameterized.expand(["invalid", "whsec_!", "whsec_YQ==", "whsec_" + base64.b64encode(b"a" * 65).decode()])
    def test_rejects_invalid_signing_secrets(self, secret: str) -> None:
        with self.assertRaises(ValidationError):
            signing_key(secret)

    @parameterized.expand([(200, "wrong"), (302, "echo"), (500, "echo"), (200, "oversized")])
    def test_callback_must_echo_the_signed_challenge(self, status: int, mode: str) -> None:
        secret = "whsec_" + base64.b64encode(b"a" * 32).decode()
        response = MagicMock()
        response.status_code = status
        session = MagicMock()

        def respond(*args: object, **kwargs: object) -> MagicMock:
            challenge = json.loads(str(kwargs["data"]))["challenge"]
            payload = {"challenge": challenge if mode == "echo" else "wrong"}
            raw = b"x" * 9000 if mode == "oversized" else json.dumps(payload).encode()
            response.iter_content.return_value = [raw]
            manager = MagicMock()
            manager.__enter__.return_value = response
            return manager

        session.post.side_effect = respond
        with patch("products.cdp.backend.mcp_event_delivery.pinned_session") as pinned:
            pinned.return_value.__enter__.return_value = session
            with self.assertRaises(MCPCallbackError):
                verify_callback(subscription_id="test-subscription", url="https://example.com/callback", secret=secret)


class TestMCPEventPropertyMasking(SimpleTestCase):
    @parameterized.expand(
        [
            (
                {"$groups": {"organization": "hidden", "project": "visible"}},
                {"$groups.organization"},
                {"$groups": {"project": "visible"}},
            ),
            (
                {"$groups.organization": "hidden", "$groups%2Eorganization": "hidden", "plan": "visible"},
                {"$groups.organization"},
                {"plan": "visible"},
            ),
            (
                {
                    "customer": {"ssn": "hidden"},
                    "customer.ssn": "hidden",
                    "customer%2Essn": "hidden",
                    "customer_name": "visible",
                },
                {"customer"},
                {"customer_name": "visible"},
            ),
            (
                {"customer%2Eprofile": {"ssn": "hidden", "public": "visible"}, "customer.profile.ssn.child": "hidden"},
                {"customer.profile.ssn"},
                {"customer%2Eprofile": {"public": "visible"}},
            ),
            (
                {"items": [{"secret": "hidden", "public": "visible"}]},
                {"items.secret"},
                {"items": [{"public": "visible"}]},
            ),
            (
                {
                    "$feature/secret": True,
                    "$active_feature_flags": ["secret", "public"],
                    "$feature_flags": {"secret": True, "public": False},
                },
                {"$feature/secret"},
                {"$active_feature_flags": ["public"], "$feature_flags": {"public": False}},
            ),
        ]
    )
    def test_redacts_restricted_paths_and_feature_flag_aliases(
        self, properties: dict[str, JsonValue], restrictions: set[str], expected: dict[str, JsonValue]
    ) -> None:
        original = json.loads(json.dumps(properties))
        self.assertEqual(MCPEventPropertyAccess.redact(properties, restrictions), expected)
        self.assertEqual(properties, original)


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
        HogFunctionTemplate.objects.create(
            template_id="template-webhook",
            sha="mcp-test",
            name="Webhook",
            code="fetch(inputs.url, {'headers': inputs.headers, 'body': inputs.body, 'method': inputs.method, 'standard_webhooks': {'secret_input': 'signing_secret'}});",
            type="destination",
            status="stable",
            inputs_schema=[
                {"key": "url", "type": "string", "required": True, "label": "URL"},
                {"key": "method", "type": "string", "required": True, "label": "Method"},
                {"key": "headers", "type": "dictionary", "label": "Headers"},
                {"key": "body", "type": "json", "label": "Body"},
                {"key": "debug", "type": "boolean", "default": False, "label": "Debug"},
                {"key": "signing_secret", "type": "string", "secret": True, "required": True, "label": "Secret"},
            ],
        )

    def subscribe(self) -> MCPEventSubscription:
        response = self.client.post(
            self.url + "subscribe/", self.payload, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]
        )
        self.assertEqual(response.status_code, 200, response.json())
        self.assertNotIn(self.secret, json.dumps(response.json()))
        return MCPEventSubscription.objects.for_team(self.team.pk).get(id=response.json()["id"])

    def authorize(
        self,
        subscription: MCPEventSubscription,
        generation: object | None = None,
        filter_bytecode: list[JsonValue] | None = None,
    ) -> "_MonkeyPatchedResponse":
        body = {
            "eventId": "a5524ac5-d7c5-43b6-862c-f5971da694c8",
            "name": "posthog.event_captured",
            "timestamp": timezone.now().isoformat(),
            "data": {"event": "example_event", "distinct_id": "sample-user", "properties": {"plan": "enterprise"}},
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
    def test_refresh_reuses_destination_and_unsubscribe_blocks_queued_delivery(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        first_function_id = subscription.hog_function_id
        first_generation = subscription.generation
        self.assertIn("mcpEventFetch(", subscription.hog_function.hog)
        self.assertEqual(self.flag_mock.call_args.args[1], self.user.distinct_id)
        verified_at = timezone.now() - timedelta(minutes=30)
        subscription.verified_at = verified_at
        subscription.save(update_fields=["verified_at"])
        self.assertNotIn(self.key, json.dumps(subscription.hog_function.inputs))
        self.assertEqual(subscription.hog_function.encrypted_inputs["mcp_credential"]["value"], self.key)
        refreshed = self.subscribe()
        self.assertEqual(refreshed.pk, subscription.pk)
        self.assertEqual(refreshed.hog_function_id, first_function_id)
        self.assertEqual(refreshed.generation, first_generation)
        self.assertEqual(refreshed.verified_at, verified_at)

        stopped = {
            **self.payload,
            "delivery": {"mode": "webhook", "url": self.callback_url},
        }
        for _ in range(2):
            response = self.client.post(
                self.url + "unsubscribe/", stopped, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]
            )
            self.assertEqual(response.status_code, 200, response.json())
        subscription.refresh_from_db()
        subscription.hog_function.refresh_from_db()
        self.assertFalse(subscription.active)
        self.assertFalse(subscription.hog_function.enabled)
        response = self.authorize(subscription, first_generation)
        self.assertEqual(response.status_code, 403, response.json())

    def test_delivery_uses_event_id_and_refresh_rotates_signatures(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        response = self.authorize(subscription)
        self.assertEqual(response.status_code, 200, response.json())
        result = response.json()
        event_id = json.loads(result["body"])["eventId"]
        self.assertEqual(result["headers"]["webhook-id"], event_id)
        self.assertNotIn(self.secret, json.dumps(result))

        self.payload["delivery"] = {
            "mode": "webhook",
            "url": self.callback_url,
            "secret": "whsec_" + base64.b64encode(b"b" * 32).decode(),
        }
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        response = self.authorize(subscription)
        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(len(response.json()["headers"]["webhook-signature"].split()), 2)

    def test_expired_subscription_and_stale_generation_cannot_deliver(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        subscription.expires_at = timezone.now() - timedelta(seconds=1)
        subscription.save(update_fields=["expires_at"])
        response = self.authorize(subscription)
        self.assertEqual(response.status_code, 403, response.json())
        old_generation = subscription.generation
        self.assertEqual(MCPEventSubscriptions.expire(), 1)
        subscription.refresh_from_db()
        subscription.hog_function.refresh_from_db()
        self.assertFalse(subscription.active)
        self.assertFalse(subscription.hog_function.enabled)
        refreshed = self.subscribe()
        self.assertNotEqual(refreshed.generation, old_generation)
        response = self.authorize(refreshed, old_generation)
        self.assertEqual(response.status_code, 403, response.json())

    def test_subscription_cannot_be_accessed_by_another_owner(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        other_user = self._create_user("other@example.com")
        self.client.force_login(other_user)
        self.assertEqual(self.client.get(self.url + str(subscription.pk) + "/").status_code, 404)

    def test_generic_destination_api_cannot_modify_subscription(self) -> None:
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        key = self.create_personal_api_key_with_scopes(["hog_function:write"])
        response = self.client.patch(
            f"/api/projects/{self.team.pk}/hog_functions/{subscription.hog_function_id}/",
            {"enabled": False},
            HTTP_AUTHORIZATION=f"Bearer {key}",
        )
        self.assertEqual(response.status_code, 403, response.json())

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

    def test_callback_failure_leaves_no_subscription_or_destination(self) -> None:
        with patch("products.cdp.backend.mcp_events.verify_callback", side_effect=MCPCallbackError("timeout")):
            response = self.client.post(
                self.url + "subscribe/", self.payload, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]
            )
        self.assertEqual(response.status_code, 400, response.json())
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())
        self.assertFalse(HogFunction.objects.filter(team=self.team).exists())

    @parameterized.expand(
        [
            (
                "event",
                PropertyDefinition.Type.EVENT,
                {"key": "plan", "type": "event", "operator": "exact", "value": "enterprise"},
            ),
            (
                "person",
                PropertyDefinition.Type.PERSON,
                {"key": "plan", "type": "person", "operator": "exact", "value": "enterprise"},
            ),
            (
                "pdi_field",
                PropertyDefinition.Type.PERSON,
                {"type": "hogql", "key": "pdi.person.properties.plan = 'enterprise'"},
            ),
            (
                "pdi_properties",
                PropertyDefinition.Type.PERSON,
                {"type": "hogql", "key": "pdi.person.properties IS NOT NULL"},
            ),
            ("pdi_person", PropertyDefinition.Type.PERSON, {"type": "hogql", "key": "pdi.person IS NOT NULL"}),
            ("pdi", PropertyDefinition.Type.PERSON, {"type": "hogql", "key": "pdi IS NOT NULL"}),
        ]
    )
    def test_property_restrictions_apply_to_creation_and_delivery(
        self, _name: str, property_type: int, property_filter: dict[str, JsonValue]
    ) -> None:
        subscription = self.subscribe()
        self.payload["arguments"] = {
            "project_id": self.team.pk,
            "filters": {
                "events": [{"id": "example_event", "type": "events"}],
                "properties": [property_filter],
            },
        }
        filtered_subscription = self.subscribe()
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="plan", property_type="String", type=property_type
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")
        response = self.authorize(subscription)
        self.assertEqual(response.status_code, 200, response.json())
        expected = {} if property_type == PropertyDefinition.Type.EVENT else {"plan": "enterprise"}
        self.assertEqual(json.loads(response.json()["body"])["data"]["properties"], expected)
        forbidden = self.authorize(filtered_subscription)
        self.assertEqual(forbidden.status_code, 403, forbidden.json())
        creation = self.client.post(
            self.url + "subscribe/", self.payload, HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"]
        )
        self.assertEqual(creation.status_code, 403, creation.json())

    @parameterized.expand(["test_account", "action"])
    def test_filter_refresh_authorizes_new_filters_and_rejects_stale_queued_filters(self, source: str) -> None:
        original = [{"key": "plan", "type": "event", "operator": "exact", "value": "internal"}]
        updated = [{"key": "next_plan", "type": "event", "operator": "exact", "value": "internal"}]
        if source == "action":
            action = Action.objects.create(
                team=self.team, name="Example action", steps_json=[{"event": "example_event", "properties": original}]
            )
            filters: dict[str, JsonValue] = {"actions": [{"id": str(action.id), "type": "actions"}]}
        else:
            self.team.test_account_filters = original
            self.team.save()
            filters = {"events": [{"id": "example_event", "type": "events"}], "filter_test_accounts": True}
        self.payload["arguments"] = {"project_id": self.team.pk, "filters": filters}
        subscription = self.subscribe()
        assert subscription.hog_function is not None
        assert subscription.hog_function.filters is not None
        queued_bytecode = deepcopy(subscription.hog_function.filters["bytecode"])
        if source == "action":
            action.steps_json = [{"event": "example_event", "properties": updated}]
            action.save()
            self.assertEqual(refresh_affected_hog_functions(action_id=action.pk), 1)
        else:
            self.team.test_account_filters = updated
            self.team.save()
            self.assertEqual(refresh_affected_hog_functions(team_id=self.team.pk), 1)
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="plan", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")
        self.assertEqual(self.authorize(subscription, filter_bytecode=queued_bytecode).status_code, 403)
        subscription.refresh_from_db()
        self.assertTrue(subscription.active)
        current = self.authorize(subscription)
        self.assertEqual(current.status_code, 200, current.json())
        next_definition = PropertyDefinition.objects.create(
            team=self.team, name="next_plan", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=next_definition, access_level="none")
        restricted = self.authorize(subscription)
        self.assertEqual(restricted.status_code, 403, restricted.json())

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

    def test_deleting_subscriber_disables_the_managed_destination(self) -> None:
        subscription = self.subscribe()
        function_id = subscription.hog_function_id
        assert function_id is not None
        self.user.delete()
        function = HogFunction.objects.get(pk=function_id)
        self.assertFalse(function.enabled)
        self.assertFalse(function.encrypted_inputs)

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

    def test_worker_reload_is_scheduled_after_commit(self) -> None:
        with patch("products.cdp.backend.mcp_events.reload_hog_functions_on_workers") as reload:
            with self.captureOnCommitCallbacks(execute=True):
                subscription = self.subscribe()
                assert subscription.hog_function is not None
                reload.assert_not_called()
            reload.assert_called_once_with(team_id=self.team.pk, hog_function_ids=[str(subscription.hog_function_id)])

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


class TestMCPEventPreview(ClickhouseTestMixin, MCPEventSubscriptionTestCase):
    def test_event_preview_reuses_filters_and_redacts_properties_without_creating_subscription(self) -> None:
        key = self.create_personal_api_key_with_scopes(["query:read"])
        self.headers = {"HTTP_AUTHORIZATION": f"Bearer {key}"}
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="plan", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(team=self.team, property_definition=definition, access_level="none")
        matching_id = UUID("a5524ac5-d7c5-43b6-862c-f5971da694c8")
        for event_uuid, event, rating in [
            (matching_id, "example_event", 2),
            (UUID("d3698028-e9a9-41e6-b44f-f7d0dc140cc5"), "example_event", 5),
            (UUID("e156c31c-726a-4c62-a40d-04dcc136c187"), "other_event", 2),
        ]:
            create_event(
                event_uuid=event_uuid,
                event=event,
                team=self.team,
                distinct_id="sample-user",
                timestamp=timezone.now(),
                properties={"rating": rating, "plan": "enterprise"},
            )
        with (
            tags_context(product=None, feature=None),
            patch("posthog.clickhouse.client.execute.DEBUG", True),
            patch("posthog.clickhouse.client.execute.TEST", False),
        ):
            response = self.client.post(
                self.url + "preview/",
                {
                    "project_id": self.team.pk,
                    "filters": {
                        "events": [{"id": "example_event", "type": "events"}],
                        "properties": [{"key": "rating", "type": "event", "operator": "lt", "value": 3}],
                    },
                },
                HTTP_AUTHORIZATION=self.headers["HTTP_AUTHORIZATION"],
            )
        self.assertEqual(response.status_code, 200, response.json())
        examples = response.json()["examples"]
        self.assertEqual(len(examples), 1)
        self.assertEqual(examples[0]["eventId"], str(matching_id))
        self.assertEqual(examples[0]["data"]["properties"], {"rating": 2})
        self.assertIsNone(examples[0]["cursor"])
        self.assertFalse(MCPEventSubscription.objects.for_team(self.team.pk).exists())

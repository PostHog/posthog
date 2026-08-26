from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.apps import apps

from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Organization, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.utils import generate_random_token_secret
from posthog.test.persons import create_group

from products.customer_analytics.backend.models import (
    Account,
    AccountRelationship,
    AccountRelationshipDefinition,
    CustomPropertySource,
    CustomPropertyValue,
    DisplayType,
)
from products.customer_analytics.backend.models.account import AccountProperties
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition

_SYNC_EXECUTE = "products.customer_analytics.backend.logic.custom_property_sync.execute_hogql_query"


class _SyncResponse:
    def __init__(self, results):
        self.results = results


class TestExternalAccountAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token"])
        # Fresh client so requests are unauthenticated unless they carry the Bearer token.
        self.client = APIClient()
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        self.csm_definition = AccountRelationshipDefinition.objects.for_team(self.team.id).create(
            team_id=self.team.id, name="CSM"
        )
        self.csm_key = str(self.csm_definition.id)
        self.url = "/api/customer_analytics/external/account"
        csp_enabled = patch(
            "products.customer_analytics.backend.presentation.views.external.posthoganalytics.feature_enabled",
            return_value=True,
        )
        self.mock_csp_enabled = csp_enabled.start()
        self.addCleanup(csp_enabled.stop)

    def _auth_headers(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.team.secret_api_token}"}

    def _get(self, external_id="acme-1", token=None):
        return self.client.get(self.url, data={"external_id": external_id}, **self._auth_headers(token))

    def _patch(self, payload, token=None):
        return self.client.patch(self.url, data=payload, format="json", **self._auth_headers(token))

    def _assign_csm(self, user):
        return AccountRelationship.objects.for_team(self.team.id).create(
            team_id=self.team.id, definition=self.csm_definition, account=self.account, user=user
        )

    def _active_csm_user_ids(self):
        return list(
            AccountRelationship.objects.for_team(self.team.id)
            .filter(account=self.account, definition=self.csm_definition, ended_at__isnull=True)
            .values_list("user_id", flat=True)
        )

    # -- Authentication ---------------------------------------------------

    def test_get_requires_auth(self):
        response = self.client.get(self.url, data={"external_id": "acme-1"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @parameterized.expand(
        [
            ("no_header", ""),
            ("bad_scheme", "Basic abc123"),
            ("empty_bearer", "Bearer "),
            ("wrong_token", "Bearer phs_wrong_token"),
        ]
    )
    def test_get_rejects_invalid_auth(self, _name, auth_value):
        headers = {"HTTP_AUTHORIZATION": auth_value} if auth_value else {}
        response = self.client.get(self.url, data={"external_id": "acme-1"}, **headers)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_rejects_public_api_token(self):
        response = self._get(token=self.team.api_token)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_accepts_backup_token(self):
        backup_token = generate_random_token_secret()
        self.team.secret_api_token_backup = backup_token
        self.team.save(update_fields=["secret_api_token_backup"])
        response = self._get(token=backup_token)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_rejects_team_without_customer_analytics_enabled(self):
        self.mock_csp_enabled.return_value = False
        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    # -- GET account ------------------------------------------------------

    def test_get_requires_external_id(self):
        response = self.client.get(self.url, **self._auth_headers())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_get_account_not_found(self):
        response = self._get(external_id="does-not-exist")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_get_account_returns_fields(self):
        self.account.churned_at = datetime(2026, 8, 1, 12, 30, tzinfo=UTC)
        self.account.save(update_fields=["churned_at"])

        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["id"], str(self.account.id))
        self.assertEqual(data["external_id"], "acme-1")
        self.assertEqual(data["name"], "Acme Corp")
        self.assertEqual(data["churned_at"], "2026-08-01T12:30:00Z")
        self.assertIsNone(data["ignored_at"])
        self.assertEqual(data["relationships"], {})

    def test_get_account_returns_active_relationships(self):
        self._assign_csm(self.user)

        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["relationships"],
            {"CSM": [{"user_id": self.user.id, "email": self.user.email}]},
        )

    def test_get_account_returns_custom_properties(self):
        plan = create_custom_property_definition(team_id=self.team.id, name="Plan", display_type=DisplayType.TEXT)
        create_custom_property_definition(team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER)
        renewal = create_custom_property_definition(
            team_id=self.team.id, name="Renewal", display_type=DisplayType.DATETIME
        )
        CustomPropertyValue.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            account=self.account,
            definition=plan,
            value_str="enterprise",
        )
        CustomPropertyValue.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            account=self.account,
            definition=renewal,
            value_datetime=datetime(2026, 7, 1, 12, 0, tzinfo=UTC),
        )

        response = self._get()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["custom_properties"],
            {"Plan": "enterprise", "Seats": None, "Renewal": "2026-07-01T12:00:00+00:00"},
        )

    def test_does_not_leak_accounts_from_other_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_team.secret_api_token = generate_random_token_secret()
        other_team.save(update_fields=["secret_api_token"])

        response = self._get(token=other_team.secret_api_token)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -- PATCH account ----------------------------------------------------

    def test_patch_requires_auth(self):
        response = self.client.patch(self.url, data={"external_id": "acme-1"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_patch_sets_and_clears_churned_at(self):
        response = self._patch({"external_id": "acme-1", "churned_at": "2026-08-02T09:00:00Z"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["churned_at"], "2026-08-02T09:00:00Z")
        self.account.refresh_from_db()
        assert self.account.churned_at is not None
        self.assertEqual(self.account.churned_at.isoformat(), "2026-08-02T09:00:00+00:00")

        response = self._patch({"external_id": "acme-1", "churned_at": None})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["churned_at"])
        self.account.refresh_from_db()
        self.assertIsNone(self.account.churned_at)

    def test_patch_requires_external_id(self):
        response = self._patch({"tags": ["enterprise"]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_account_not_found(self):
        response = self._patch({"external_id": "does-not-exist", "tags": ["enterprise"]})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_assigns_relationship_and_returns_it(self):
        response = self._patch(
            {"external_id": "acme-1", "relationships": {self.csm_key: {"type": "user", "id": self.user.id}}}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json()["relationships"],
            {"CSM": [{"user_id": self.user.id, "email": self.user.email}]},
        )
        self.assertEqual(self._active_csm_user_ids(), [self.user.id])

    def test_patch_null_ends_active_assignment(self):
        self._assign_csm(self.user)

        response = self._patch({"external_id": "acme-1", "relationships": {self.csm_key: None}})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["relationships"], {})
        self.assertEqual(self._active_csm_user_ids(), [])

    def test_patch_relationships_do_not_touch_properties(self):
        self.account.properties = AccountProperties(stripe_customer_id="cus_123")
        self.account.save(update_fields=["_properties"])

        response = self._patch(
            {"external_id": "acme-1", "relationships": {self.csm_key: {"type": "user", "id": self.user.id}}}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["properties"]["stripe_customer_id"], "cus_123")

    @parameterized.expand(
        [
            ("role_assignee", {"type": "role", "id": "some-role-uuid"}),
            ("not_an_object", "someone@example.com"),
            ("bad_id", {"type": "user", "id": {"nested": True}}),
        ]
    )
    def test_patch_rejects_invalid_assignee(self, _name, assignee):
        response = self._patch({"external_id": "acme-1", "relationships": {self.csm_key: assignee}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._active_csm_user_ids(), [])

    def test_patch_rejects_non_uuid_key(self):
        response = self._patch({"external_id": "acme-1", "relationships": {"AE": {"type": "user", "id": self.user.id}}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "AE: no relationship definition with this ID")

    def test_patch_rejects_non_member_user(self):
        other_org = Organization.objects.create(name="Outsiders")
        outsider = User.objects.create_and_join(other_org, "outsider@example.com", None)
        response = self._patch(
            {"external_id": "acme-1", "relationships": {self.csm_key: {"type": "user", "id": outsider.id}}}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], f"{self.csm_key}: user is not a member of this organization")
        self.assertEqual(self._active_csm_user_ids(), [])

    def test_patch_adds_tags_by_default(self):
        self._patch({"external_id": "acme-1", "tags": ["enterprise"]})
        response = self._patch({"external_id": "acme-1", "tags": ["priority"]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["enterprise", "priority"])

    def test_patch_sets_tags_replacing_existing(self):
        self._patch({"external_id": "acme-1", "tags": ["enterprise"]})
        response = self._patch({"external_id": "acme-1", "tags": ["priority"], "tags_mode": "set"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["priority"])

    def test_patch_removes_tags(self):
        self._patch({"external_id": "acme-1", "tags": ["enterprise", "priority"]})
        response = self._patch({"external_id": "acme-1", "tags": ["priority"], "tags_mode": "remove"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], ["enterprise"])

    @patch("products.customer_analytics.backend.events.capture_batch_internal")
    def test_patch_with_workflow_header_attributes_tag_added_event(self, mock_capture):
        workflow_id = str(uuid4())
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                self.url,
                data={"external_id": "acme-1", "tags": ["vip"]},
                format="json",
                HTTP_X_POSTHOG_HOG_FLOW_ID=workflow_id,
                **self._auth_headers(),
            )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        (event,) = mock_capture.call_args.kwargs["events"]
        self.assertEqual(event["properties"]["actor_type"], "workflow")
        self.assertEqual(event["properties"]["workflow_id"], workflow_id)

    def test_patch_does_not_update_other_team_account(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_team.secret_api_token = generate_random_token_secret()
        other_team.save(update_fields=["secret_api_token"])

        response = self._patch({"external_id": "acme-1", "tags": ["enterprise"]}, token=other_team.secret_api_token)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_rolls_back_relationship_assignment_when_tags_fail(self):
        with patch(
            "products.customer_analytics.backend.facade.api._apply_external_tags",
            side_effect=Exception("boom"),
        ):
            response = self._patch(
                {
                    "external_id": "acme-1",
                    "relationships": {self.csm_key: {"type": "user", "id": self.user.id}},
                    "tags": ["enterprise"],
                }
            )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._active_csm_user_ids(), [])

    def test_patch_cannot_change_external_id_or_name(self):
        # external_id only identifies the account; renaming/rebinding is not exposed to workflows.
        response = self._patch({"external_id": "acme-1", "name": "Renamed", "new_external_id": "acme-2"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.account.refresh_from_db()
        self.assertEqual(self.account.external_id, "acme-1")
        self.assertEqual(self.account.name, "Acme Corp")

    def test_patch_unexpected_exception_captures_with_team_and_external_id(self):
        with (
            patch(
                "products.customer_analytics.backend.facade.api._apply_external_tags",
                side_effect=RuntimeError("db exploded"),
            ),
            patch("products.customer_analytics.backend.facade.api.capture_exception") as mock_capture,
        ):
            self._patch({"external_id": "acme-1", "tags": ["enterprise"]})

        mock_capture.assert_called_once()
        _exc, context = mock_capture.call_args[0]
        self.assertEqual(context["team_id"], self.team.id)
        self.assertEqual(context["external_id"], "acme-1")

    def test_patch_relationship_definition_not_found_does_not_capture(self):
        with patch("products.customer_analytics.backend.facade.api.capture_exception") as mock_capture:
            response = self._patch(
                {"external_id": "acme-1", "relationships": {"AE": {"type": "user", "id": self.user.id}}}
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_capture.assert_not_called()

    def test_patch_rejects_unknown_uuid_key(self):
        unknown_uuid = "00000000-0000-0000-0000-000000000099"
        response = self._patch(
            {"external_id": "acme-1", "relationships": {unknown_uuid: {"type": "user", "id": self.user.id}}}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(unknown_uuid, response.json()["error"])

    # -- Create (POST) ----------------------------------------------------

    def _post(self, payload, token=None, **extra):
        return self.client.post(self.url, data=payload, format="json", **self._auth_headers(token), **extra)

    def test_post_requires_auth(self):
        response = self.client.post(self.url, data={"external_id": "new-1"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_post_creates_account_named_after_its_group(self):
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save()
        create_group(team=self.team, group_type_index=0, group_key="new-1", group_properties={"name": "New Corp"})

        response = self._post({"external_id": "new-1"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body["external_id"], "new-1")
        self.assertEqual(body["name"], "New Corp")
        account = Account.objects.for_team(self.team.id).get(external_id="new-1")
        self.assertEqual(account.name, "New Corp")
        self.assertIsNone(account.created_by)

    @parameterized.expand(
        [
            ("no_group_type_configured", False, False),
            ("group_missing", True, False),
            ("group_has_no_name_property", True, True),
        ]
    )
    def test_post_name_falls_back_to_external_id(self, _name, configure_group_type, create_nameless_group):
        if configure_group_type:
            self.team.customer_analytics_config.account_group_type_index = 0
            self.team.customer_analytics_config.save()
        if create_nameless_group:
            create_group(team=self.team, group_type_index=0, group_key="new-1", group_properties={"plan": "free"})

        response = self._post({"external_id": "new-1"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["name"], "new-1")

    def test_post_existing_account_is_a_noop(self):
        response = self._post({"external_id": "acme-1"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "Acme Corp")
        self.account.refresh_from_db()
        self.assertEqual(self.account.name, "Acme Corp")

    @parameterized.expand([("missing", {}), ("blank", {"external_id": "   "})])
    def test_post_requires_external_id(self, _name, payload):
        response = self._post(payload)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_with_workflow_header_attributes_activity_to_workflow(self):
        workflow_id = str(uuid4())
        response = self._post({"external_id": "new-1"}, HTTP_X_POSTHOG_HOG_FLOW_ID=workflow_id)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        log = ActivityLog.objects.get(team_id=self.team.id, scope="Account", activity="created")
        self.assertIsNone(log.user)
        detail = log.detail
        assert detail is not None
        self.assertEqual(detail["trigger"]["job_type"], "hog_flow")
        self.assertEqual(detail["trigger"]["job_id"], workflow_id)

    def test_post_does_not_see_other_teams_account(self):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        create_account(team_id=other_team.id, name="Other Team Corp", external_id="shared-key")
        response = self._post({"external_id": "shared-key"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Account.objects.for_team(self.team.id).get(external_id="shared-key").name, "shared-key")

    def _create_warehouse_backed_property(self):
        DataWarehouseTable = apps.get_model("warehouse_sources", "DataWarehouseTable")
        DataWarehouseSavedQuery = apps.get_model("data_modeling", "DataWarehouseSavedQuery")
        table = DataWarehouseTable.objects.create(team=self.team, name="billing_view_mat", columns={})
        view = DataWarehouseSavedQuery.objects.create(
            team=self.team, name="billing_view", columns={"org_id": {}, "mrr": {}}, table=table
        )
        definition = create_custom_property_definition(
            team_id=self.team.id, name="MRR", display_type=DisplayType.NUMBER
        )
        return CustomPropertySource.objects.unscoped().create(
            team=self.team, definition=definition, saved_query=view, source_column="mrr", key_column="org_id"
        )

    def test_post_from_workflow_returns_warehouse_custom_properties_synced_on_create(self):
        self._create_warehouse_backed_property()
        # selected columns are sorted: mrr, org_id
        with patch(_SYNC_EXECUTE, return_value=_SyncResponse([(100.0, "new-1")])):
            response = self._post({"external_id": "new-1"}, HTTP_X_POSTHOG_HOG_FLOW_ID=str(uuid4()))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["custom_properties"]["MRR"], 100.0)

    def test_post_succeeds_when_property_sync_fails(self):
        self._create_warehouse_backed_property()
        with patch(_SYNC_EXECUTE, side_effect=Exception("clickhouse down")):
            response = self._post({"external_id": "new-1"}, HTTP_X_POSTHOG_HOG_FLOW_ID=str(uuid4()))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.json()["custom_properties"]["MRR"])

    def test_post_without_workflow_header_does_not_sync(self):
        self._create_warehouse_backed_property()
        with patch(_SYNC_EXECUTE) as execute:
            response = self._post({"external_id": "new-1"})

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        execute.assert_not_called()

    def test_post_existing_account_does_not_sync(self):
        self._create_warehouse_backed_property()
        with patch(_SYNC_EXECUTE) as execute:
            response = self._post({"external_id": "acme-1"}, HTTP_X_POSTHOG_HOG_FLOW_ID=str(uuid4()))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        execute.assert_not_called()


class TestExternalAccountCustomPropertiesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.team.secret_api_token = generate_random_token_secret()
        self.team.save(update_fields=["secret_api_token"])
        self.client = APIClient()
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        self.plan = create_custom_property_definition(team_id=self.team.id, name="Plan", display_type=DisplayType.TEXT)
        self.seats = create_custom_property_definition(
            team_id=self.team.id, name="Seats", display_type=DisplayType.NUMBER
        )
        self.url = "/api/customer_analytics/external/account/custom_property_values"
        csp_enabled = patch(
            "products.customer_analytics.backend.presentation.views.external.posthoganalytics.feature_enabled",
            return_value=True,
        )
        csp_enabled.start()
        self.addCleanup(csp_enabled.stop)

    def _auth_headers(self, token=None):
        return {"HTTP_AUTHORIZATION": f"Bearer {token or self.team.secret_api_token}"}

    def _patch(self, payload, token=None):
        return self.client.patch(self.url, data=payload, format="json", **self._auth_headers(token))

    def test_requires_auth(self):
        response = self.client.patch(self.url, data={"external_id": "acme-1", "properties": {}}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_sets_values_by_definition_id(self):
        response = self._patch(
            {"external_id": "acme-1", "properties": {str(self.plan.id): "enterprise", str(self.seats.id): 42}}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        active = CustomPropertyValue.objects.for_team(self.team.id).filter(account=self.account, is_deleted=False)
        self.assertEqual(
            {(v.definition.name, v.value_str, v.value_num) for v in active},
            {
                ("Plan", "enterprise", None),
                ("Seats", None, 42.0),
            },
        )

    def test_unknown_external_id_returns_404(self):
        response = self._patch({"external_id": "missing", "properties": {str(self.plan.id): "x"}})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_unknown_definition_id_returns_400(self):
        response = self._patch({"external_id": "acme-1", "properties": {str(uuid4()): "x"}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_rejects_non_scalar_value(self):
        response = self._patch({"external_id": "acme-1", "properties": {str(self.plan.id): {"nested": "object"}}})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unexpected_exception_captures_with_team_and_external_id(self):
        with (
            patch(
                "products.customer_analytics.backend.logic.custom_property_values.set_account_custom_properties_by_id",
                side_effect=RuntimeError("db exploded"),
            ),
            patch("products.customer_analytics.backend.facade.api.capture_exception") as mock_capture,
        ):
            self._patch({"external_id": "acme-1", "properties": {str(self.plan.id): "enterprise"}})

        mock_capture.assert_called_once()
        _exc, context = mock_capture.call_args[0]
        self.assertEqual(context["team_id"], self.team.id)
        self.assertEqual(context["external_id"], "acme-1")

    def test_unknown_definition_does_not_capture(self):
        with patch("products.customer_analytics.backend.facade.api.capture_exception") as mock_capture:
            response = self._patch({"external_id": "acme-1", "properties": {str(uuid4()): "x"}})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_capture.assert_not_called()

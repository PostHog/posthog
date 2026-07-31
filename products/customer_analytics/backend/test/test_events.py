from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction

from parameterized import parameterized

from posthog.api.capture import CaptureInternalResult
from posthog.rbac.user_access_control import UserAccessControl
from posthog.test.persons import create_group_type_mapping

from products.customer_analytics.backend.facade import (
    api as facade,
    contracts,
)
from products.customer_analytics.backend.test.factories import create_account, create_custom_property_definition


@patch("products.customer_analytics.backend.events.capture_batch_internal")
class TestAccountTagAddedEvent(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")

    def _add_tags(self, tags, tags_mode="add"):
        with self.captureOnCommitCallbacks(execute=True):
            result = facade.update_external_account(
                self.team.id, "acme-1", relationship_assignments={}, tags=tags, tags_mode=tags_mode
            )
        assert result.error is None

    def test_external_tag_add_emits_one_event_with_account_groups(self, mock_capture):
        create_group_type_mapping(team=self.team, project=self.team.project, group_type="account", group_type_index=1)
        config = self.team.customer_analytics_config
        config.account_group_type_index = 1
        config.save()

        self._add_tags(["enterprise"])

        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["token"] == self.team.api_token
        (event,) = kwargs["events"]
        assert event["event"] == "$account_tag_added"
        assert event["distinct_id"] == f"account:{self.account.id}"
        properties = event["properties"]
        assert properties["tag"] == "enterprise"
        assert properties["account_id"] == str(self.account.id)
        assert properties["account_external_id"] == "acme-1"
        assert properties["account_name"] == "Acme Corp"
        assert properties["actor_type"] == "system"
        assert properties["$groups"] == {"account": "acme-1"}

    def test_re_adding_existing_tag_emits_nothing(self, mock_capture):
        self._add_tags(["enterprise"])
        mock_capture.reset_mock()

        self._add_tags(["enterprise"])

        mock_capture.assert_not_called()

    def test_set_mode_emits_only_newly_added_tags(self, mock_capture):
        self._add_tags(["old"])
        mock_capture.reset_mock()

        self._add_tags(["old", "new"], tags_mode="set")

        mock_capture.assert_called_once()
        (event,) = mock_capture.call_args.kwargs["events"]
        assert event["properties"]["tag"] == "new"

    def test_view_update_emits_with_user_actor(self, mock_capture):
        with self.captureOnCommitCallbacks(execute=True):
            facade.update_account_for_view(
                team_id=self.team.id,
                account_id=str(self.account.id),
                input=contracts.UpdateAccountInput(tags=["enterprise"]),
                user_access_control=UserAccessControl(user=self.user, team=self.team),
                required_level="editor",
                organization_id=self.organization.id,
                user=self.user,
                was_impersonated=False,
            )

        mock_capture.assert_called_once()
        (event,) = mock_capture.call_args.kwargs["events"]
        assert event["properties"]["actor_type"] == "user"
        assert event["properties"]["actor_email"] == self.user.email

    def test_event_without_account_group_type_has_no_groups(self, mock_capture):
        self._add_tags(["enterprise"])

        mock_capture.assert_called_once()
        (event,) = mock_capture.call_args.kwargs["events"]
        assert "$groups" not in event["properties"]

    def test_no_event_when_transaction_rolls_back(self, mock_capture):
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    facade.update_external_account(
                        self.team.id, "acme-1", relationship_assignments={}, tags=["enterprise"], tags_mode="add"
                    )
                    raise RuntimeError("boom")
            except RuntimeError:
                pass

        mock_capture.assert_not_called()

    def test_capture_failure_is_reported_not_raised(self, mock_capture):
        mock_capture.return_value = CaptureInternalResult(status_code=503, error={"error": "transport_error"})

        with patch("products.customer_analytics.backend.facade.api.capture_exception") as mock_capture_exception:
            self._add_tags(["enterprise"])

        mock_capture_exception.assert_called_once()


WORKFLOW_ID = "123e4567-e89b-12d3-a456-426614174000"


@patch("products.customer_analytics.backend.events.capture_batch_internal")
class TestAccountCustomPropertyChangedEvent(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")
        create_group_type_mapping(team=self.team, project=self.team.project, group_type="account", group_type_index=1)
        config = self.team.customer_analytics_config
        config.account_group_type_index = 1
        config.save()

    def _set_value(self, definition, value, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            facade.set_custom_property_value(
                team_id=self.team.id,
                account_id=str(self.account.id),
                definition_id=str(definition.id),
                value=value,
                **kwargs,
            )

    @parameterized.expand(
        [
            ("text", "silver", "gold", "silver", "gold", "string"),
            ("number", 1.5, 2.5, 1.5, 2.5, "numeric"),
            ("boolean", True, False, True, False, "boolean"),
            (
                "datetime",
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "2026-01-01T00:00:00+00:00",
                "2026-02-01T00:00:00+00:00",
                "datetime",
            ),
        ]
    )
    def test_change_emits_event_with_previous_and_current(
        self, mock_capture, display_type, initial, changed, expected_previous, expected_current, expected_data_type
    ):
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan", display_type=display_type)
        self._set_value(definition, initial)
        mock_capture.reset_mock()

        self._set_value(definition, changed)

        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["token"] == self.team.api_token
        (event,) = kwargs["events"]
        assert event["event"] == "$account_custom_property_changed"
        assert event["distinct_id"] == f"account:{self.account.id}"
        properties = event["properties"]
        assert properties["property_id"] == str(definition.id)
        assert properties["property_name"] == "Plan"
        assert properties["data_type"] == expected_data_type
        assert properties["previous_value"] == expected_previous
        assert properties["current_value"] == expected_current
        assert properties["account_id"] == str(self.account.id)
        assert properties["account_external_id"] == "acme-1"
        assert properties["account_name"] == "Acme Corp"
        assert properties["actor_type"] == "system"
        assert properties["$groups"] == {"account": "acme-1"}

    def test_first_set_emits_with_null_previous_value(self, mock_capture):
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")

        self._set_value(definition, "gold")

        mock_capture.assert_called_once()
        (event,) = mock_capture.call_args.kwargs["events"]
        assert event["event"] == "$account_custom_property_changed"
        assert event["properties"]["previous_value"] is None
        assert event["properties"]["current_value"] == "gold"

    @parameterized.expand(
        [
            ("text", "gold"),
            ("number", 1.5),
            ("boolean", True),
            ("datetime", "2026-01-01T00:00:00Z"),
        ]
    )
    def test_same_value_write_emits_nothing(self, mock_capture, display_type, value):
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan", display_type=display_type)
        self._set_value(definition, value)
        mock_capture.reset_mock()

        self._set_value(definition, value)

        mock_capture.assert_not_called()

    def test_no_event_when_transaction_rolls_back(self, mock_capture):
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        self._set_value(definition, "silver")
        mock_capture.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    facade.set_custom_property_value(
                        team_id=self.team.id,
                        account_id=str(self.account.id),
                        definition_id=str(definition.id),
                        value="gold",
                    )
                    raise RuntimeError("boom")
            except RuntimeError:
                pass

        mock_capture.assert_not_called()

    def test_capture_failure_is_reported_not_raised(self, mock_capture):
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        self._set_value(definition, "silver")
        mock_capture.reset_mock()
        mock_capture.return_value = CaptureInternalResult(status_code=503, error={"error": "transport_error"})

        with patch(
            "products.customer_analytics.backend.logic.custom_property_values.capture_exception"
        ) as mock_capture_exception:
            self._set_value(definition, "gold")

        mock_capture_exception.assert_called_once()
        (value,) = facade.list_active_custom_property_values(self.team.id, str(self.account.id))
        assert value.value == "gold"

    def test_workflow_write_sets_workflow_actor(self, mock_capture):
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        self._set_value(definition, "silver")
        mock_capture.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            result = facade.set_external_account_custom_properties(
                self.team.id, "acme-1", properties={str(definition.id): "gold"}, workflow_id=WORKFLOW_ID
            )
        assert result.error is None

        mock_capture.assert_called_once()
        (event,) = mock_capture.call_args.kwargs["events"]
        assert event["properties"]["actor_type"] == "workflow"
        assert event["properties"]["workflow_id"] == WORKFLOW_ID

    def test_user_actor_populates_actor_fields(self, mock_capture):
        definition = create_custom_property_definition(team_id=self.team.id, name="Plan")
        self._set_value(definition, "silver")
        mock_capture.reset_mock()

        self._set_value(definition, "gold", actor=self.user)

        mock_capture.assert_called_once()
        (event,) = mock_capture.call_args.kwargs["events"]
        assert event["distinct_id"] == self.user.distinct_id
        assert event["properties"]["actor_type"] == "user"
        assert event["properties"]["actor_email"] == self.user.email

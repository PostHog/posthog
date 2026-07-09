from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction

from posthog.api.capture import CaptureInternalResult
from posthog.rbac.user_access_control import UserAccessControl
from posthog.test.persons import create_group_type_mapping

from products.customer_analytics.backend.facade import (
    api as facade,
    contracts,
)
from products.customer_analytics.backend.test.factories import create_account


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

        with patch("products.customer_analytics.backend.events.capture_exception") as mock_capture_exception:
            self._add_tags(["enterprise"])

        mock_capture_exception.assert_called_once()

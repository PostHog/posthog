from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import transaction

from posthog.api.tagged_item import set_tags_on_object
from posthog.test.persons import create_group_type_mapping

from products.customer_analytics.backend.facade import api as facade
from products.customer_analytics.backend.test.factories import create_account
from products.product_analytics.backend.models.insight import Insight


@patch("products.customer_analytics.backend.events.capture_internal")
class TestAccountTagAddedEvent(BaseTest):
    def setUp(self):
        super().setUp()
        self.account = create_account(team_id=self.team.id, name="Acme Corp", external_id="acme-1")

    def _add_tags(self, tags):
        with self.captureOnCommitCallbacks(execute=True):
            result = facade.update_external_account(
                self.team.id, "acme-1", relationship_assignments={}, tags=tags, tags_mode="add"
            )
        assert result.error is None

    def test_tag_add_emits_one_event_with_account_groups(self, mock_capture):
        create_group_type_mapping(team=self.team, project=self.team.project, group_type="account", group_type_index=1)
        config = self.team.customer_analytics_config
        config.account_group_type_index = 1
        config.save()

        self._add_tags(["enterprise"])

        mock_capture.assert_called_once()
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["event_name"] == "$account_tag_added"
        assert kwargs["token"] == self.team.api_token
        properties = kwargs["properties"]
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

    def test_tag_on_non_account_object_emits_nothing(self, mock_capture):
        insight = Insight.objects.create(team=self.team)

        with self.captureOnCommitCallbacks(execute=True):
            set_tags_on_object(["enterprise"], insight)

        mock_capture.assert_not_called()

    def test_event_without_account_group_type_has_no_groups(self, mock_capture):
        self._add_tags(["enterprise"])

        mock_capture.assert_called_once()
        assert "$groups" not in mock_capture.call_args.kwargs["properties"]

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

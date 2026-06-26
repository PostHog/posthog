from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team

from products.customer_analytics.backend.logic.usage_spike_notifications import notify_managers_of_usage_spike
from products.customer_analytics.backend.test.factories import create_account
from products.notifications.backend.facade.enums import NotificationType, Priority, SourceType, TargetType

SERVICE = "products.customer_analytics.backend.logic.usage_spike_notifications"

SPIKES = [{"metric": "events", "factor": 3.2, "direction": "up", "percent_change": 220}]


@patch(f"{SERVICE}.has_been_dispatched", return_value=False)
@patch(f"{SERVICE}.create_notification")
class TestNotifyManagersOfUsageSpike(BaseTest):
    def setUp(self):
        super().setUp()
        csp_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self.mock_feature_enabled = csp_patcher.start()
        self.addCleanup(csp_patcher.stop)

    def _notify_managers(self, *, team_id: int | None = None, **kwargs):
        notify_managers_of_usage_spike(
            team_id=self.team.id if team_id is None else team_id, spike_id="spike-1", spikes=SPIKES, **kwargs
        )

    def _create_account_with_managers(self, *, csm_id: int | None = 101, ae_id: int | None = 102, **account_kwargs):
        properties: dict = {}
        if csm_id is not None:
            properties["csm"] = {"id": csm_id, "email": f"csm{csm_id}@example.com"}
        if ae_id is not None:
            properties["account_executive"] = {"id": ae_id, "email": f"ae{ae_id}@example.com"}
        return create_account(team_id=self.team.id, name="Acme Corp", properties=properties, **account_kwargs)

    @parameterized.expand(
        [
            ("external_id", {"external_id": "org-123"}, {}, {"organization_id": "org-123"}),
            ("billing_id", {}, {"billing_id": "bill-9"}, {"billing_id": "bill-9"}),
            ("stripe_customer_id", {}, {"stripe_customer_id": "cus_42"}, {"stripe_customer_id": "cus_42"}),
        ]
    )
    def test_matches_account_by_identifier(
        self, mock_create, _mock_dispatched, _name, account_kwargs, properties_extra, lookup
    ):
        account = self._create_account_with_managers(**account_kwargs)
        if properties_extra:
            account.properties = {**account.properties.model_dump(mode="json"), **properties_extra}
            account.save()

        self._notify_managers(**lookup)

        assert mock_create.call_count == 2
        target_ids = {call.args[0].target_id for call in mock_create.call_args_list}
        assert target_ids == {"101", "102"}

    def test_no_match_does_not_notify(self, mock_create, mock_dispatched):
        self._create_account_with_managers(external_id="org-123")
        self._notify_managers(organization_id="does-not-exist")
        mock_create.assert_not_called()
        mock_dispatched.assert_not_called()

    def test_account_on_other_team_is_not_matched(self, mock_create, mock_dispatched):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        create_account(
            team_id=other_team.id,
            name="Acme Corp",
            properties={"csm": {"id": 101, "email": "csm@example.com"}},
            external_id="org-123",
        )
        self._notify_managers(organization_id="org-123")
        mock_create.assert_not_called()
        mock_dispatched.assert_not_called()

    def test_account_without_managers_does_not_notify(self, mock_create, _mock_dispatched):
        self._create_account_with_managers(csm_id=None, ae_id=None, external_id="org-123")
        self._notify_managers(organization_id="org-123")
        mock_create.assert_not_called()

    def test_csp_disabled_does_not_notify(self, mock_create, mock_dispatched):
        self.mock_feature_enabled.return_value = False
        self._create_account_with_managers(external_id="org-123")
        self._notify_managers(organization_id="org-123")
        mock_create.assert_not_called()
        mock_dispatched.assert_not_called()

    def test_dispatch_never_raises_on_unexpected_error(self, mock_create, _mock_dispatched):
        with patch(f"{SERVICE}._find_account", side_effect=RuntimeError("boom")):
            self._notify_managers(organization_id="org-123")
        mock_create.assert_not_called()

    def test_dedupes_when_csm_and_ae_are_same_user(self, mock_create, _mock_dispatched):
        self._create_account_with_managers(csm_id=55, ae_id=55, external_id="org-123")
        self._notify_managers(organization_id="org-123")
        mock_create.assert_called_once()
        assert mock_create.call_args.args[0].target_id == "55"

    def test_idempotent_when_already_dispatched(self, mock_create, mock_dispatched):
        mock_dispatched.return_value = True
        self._create_account_with_managers(external_id="org-123")
        self._notify_managers(organization_id="org-123")
        mock_create.assert_not_called()

    def test_notification_content(self, mock_create, _mock_dispatched):
        account = self._create_account_with_managers(csm_id=101, ae_id=None, external_id="org-123")
        self._notify_managers(organization_id="org-123", detected_at="2026-06-09")

        data = mock_create.call_args.args[0]
        assert data.notification_type == NotificationType.USAGE_SPIKE
        assert data.priority == Priority.CRITICAL
        assert data.source_type == SourceType.CUSTOMER_ANALYTICS
        assert data.target_type == TargetType.USER
        assert data.team_id == self.team.id
        assert data.resource_id == str(account.id)
        assert data.source_id == "spike-1"
        assert data.title == "Usage spike: Acme Corp"
        assert data.body == "events 3.2× (up) — detected 2026-06-09"
        # Project-relative path; the notifications side panel adds the project prefix on navigation.
        assert data.source_url == f"/customer_analytics/accounts/{account.id}/usage"

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team, User

from products.customer_analytics.backend.logic import relationships as relationships_logic
from products.customer_analytics.backend.logic.usage_spike_notifications import notify_managers_of_usage_spike
from products.customer_analytics.backend.models import Account, AccountRelationshipDefinition
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
        self.csm_user = self._create_user("csm@example.com")
        self.ae_user = self._create_user("ae@example.com")
        self.csm_definition = self._create_definition("CSM")
        self.ae_definition = self._create_definition("Account executive")

    def _create_definition(self, name: str, team_id: int | None = None) -> AccountRelationshipDefinition:
        team_id = self.team.id if team_id is None else team_id
        return AccountRelationshipDefinition.objects.for_team(team_id).create(team_id=team_id, name=name)

    def _assign(
        self, account: Account, definition: AccountRelationshipDefinition, user: User, team_id: int | None = None
    ) -> None:
        relationships_logic.assign(
            team_id=self.team.id if team_id is None else team_id,
            account=account,
            definition=definition,
            user=user,
            created_by=None,
        )

    def _notify_managers(self, *, team_id: int | None = None, **kwargs):
        notify_managers_of_usage_spike(
            team_id=self.team.id if team_id is None else team_id, spike_id="spike-1", spikes=SPIKES, **kwargs
        )

    def _create_account_with_managers(self, **account_kwargs) -> Account:
        account = create_account(team_id=self.team.id, name="Acme Corp", **account_kwargs)
        self._assign(account, self.csm_definition, self.csm_user)
        self._assign(account, self.ae_definition, self.ae_user)
        return account

    @parameterized.expand(
        [
            ("external_id", {"external_id": "org-123"}, {"organization_id": "org-123"}),
            ("billing_id", {"properties": {"billing_id": "bill-9"}}, {"billing_id": "bill-9"}),
            ("stripe_customer_id", {"properties": {"stripe_customer_id": "cus_42"}}, {"stripe_customer_id": "cus_42"}),
        ]
    )
    def test_matches_account_by_identifier(self, mock_create, _mock_dispatched, _name, account_kwargs, lookup):
        self._create_account_with_managers(**account_kwargs)

        self._notify_managers(**lookup)

        assert mock_create.call_count == 2
        target_ids = {call.args[0].target_id for call in mock_create.call_args_list}
        assert target_ids == {str(self.csm_user.id), str(self.ae_user.id)}

    def test_no_match_does_not_notify(self, mock_create, mock_dispatched):
        self._create_account_with_managers(external_id="org-123")
        self._notify_managers(organization_id="does-not-exist")
        mock_create.assert_not_called()
        mock_dispatched.assert_not_called()

    def test_account_on_other_team_is_not_matched(self, mock_create, mock_dispatched):
        other_team = Team.objects.create(organization=self.organization, name="Other")
        other_definition = self._create_definition("CSM", team_id=other_team.id)
        account = create_account(team_id=other_team.id, name="Acme Corp", external_id="org-123")
        self._assign(account, other_definition, self.csm_user, team_id=other_team.id)

        self._notify_managers(organization_id="org-123")

        mock_create.assert_not_called()
        mock_dispatched.assert_not_called()

    def test_account_without_relationships_does_not_notify(self, mock_create, _mock_dispatched):
        create_account(team_id=self.team.id, name="Acme Corp", external_id="org-123")
        self._notify_managers(organization_id="org-123")
        mock_create.assert_not_called()

    def test_ended_assignment_is_not_notified(self, mock_create, _mock_dispatched):
        account = create_account(team_id=self.team.id, name="Acme Corp", external_id="org-123")
        self._assign(account, self.csm_definition, self.csm_user)
        self._assign(account, self.csm_definition, self.ae_user)

        self._notify_managers(organization_id="org-123")

        mock_create.assert_called_once()
        assert mock_create.call_args.args[0].target_id == str(self.ae_user.id)

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

    def test_dedupes_when_same_user_holds_multiple_relationships(self, mock_create, _mock_dispatched):
        account = create_account(team_id=self.team.id, name="Acme Corp", external_id="org-123")
        self._assign(account, self.csm_definition, self.csm_user)
        self._assign(account, self.ae_definition, self.csm_user)

        self._notify_managers(organization_id="org-123")

        mock_create.assert_called_once()
        assert mock_create.call_args.args[0].target_id == str(self.csm_user.id)

    def test_idempotent_when_already_dispatched(self, mock_create, mock_dispatched):
        mock_dispatched.return_value = True
        self._create_account_with_managers(external_id="org-123")
        self._notify_managers(organization_id="org-123")
        mock_create.assert_not_called()

    def test_notification_content(self, mock_create, _mock_dispatched):
        account = create_account(team_id=self.team.id, name="Acme Corp", external_id="org-123")
        self._assign(account, self.csm_definition, self.csm_user)

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

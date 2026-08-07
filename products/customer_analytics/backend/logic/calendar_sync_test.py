from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from products.customer_analytics.backend.logic.calendar_sync import _group_keys_via_persons, _match_accounts_for_emails
from products.customer_analytics.backend.models import Account, TeamCustomerAnalyticsConfig
from products.customer_analytics.backend.models.team_scoped_test_base import TeamScopedTestMixin

_EXECUTE = "posthog.hogql.query.execute_hogql_query"
_GET_PERSONS = "products.customer_analytics.backend.logic.calendar_sync.get_persons_by_uuids"


class _Response:
    def __init__(self, results):
        self.results = results


class CalendarSyncGroupMatchingTest(TeamScopedTestMixin, BaseTest):
    def setUp(self):
        super().setUp()
        TeamCustomerAnalyticsConfig.objects.filter(team=self.team).update(account_group_type_index=2)
        self.team.customer_analytics_config.refresh_from_db()

    def test_group_lookup_preserves_hogql_placeholder(self):
        # Regression: substituting {group_col} with str.format() also tried to bind the
        # {distinct_ids} HogQL placeholder, raising KeyError and killing the whole sync.
        person = Mock(uuid="uuid-1", distinct_ids=["did-1"])
        with (
            patch(_EXECUTE) as execute,
            patch(_GET_PERSONS, return_value=[person]),
        ):
            execute.side_effect = [
                _Response([("uuid-1", "attendee@acme.test")]),
                _Response([("did-1", "grp_key_1")]),
            ]
            result = _group_keys_via_persons(self.team, ["attendee@acme.test"], group_type_index=2)

        assert result == {"attendee@acme.test": "grp_key_1"}
        group_query = execute.call_args_list[1].args[0]
        assert "`$group_2`" in group_query
        assert "{distinct_ids}" in group_query

    def test_group_matching_failure_does_not_abort_matching(self):
        # A failure in the optional group-matching step must degrade to "no group match",
        # not propagate up and abort the sync. The domain fallback should still resolve.
        account = Account.objects.create(team=self.team, name="Acme")
        account.properties = account.properties.model_copy(update={"email_domains": ["acme.test"]})
        account.save()

        with patch(_EXECUTE, side_effect=RuntimeError("boom")):
            matched = _match_accounts_for_emails(self.team, ["attendee@acme.test"])

        assert matched == {"attendee@acme.test": account}

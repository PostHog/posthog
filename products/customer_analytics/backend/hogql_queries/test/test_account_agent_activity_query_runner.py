from typing import Any

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from posthog.schema import AccountActivityMatrixEmptyReason, AccountAgentActivityQuery

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.test.persons import create_person

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.hogql_queries.account_agent_activity_query_runner import (
    AccountAgentActivityQueryRunner,
)
from products.customer_analytics.backend.test.factories import create_account

ANA = "11111111-1111-4111-8111-111111111111"
BO = "22222222-2222-4222-8222-222222222222"
STAFF = "33333333-3333-4333-8333-333333333333"


@time_machine.travel("2026-10-28T18:00:00Z", tick=False)
class TestAccountAgentActivityQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save()
        self.account = create_account(team_id=self.team.id, external_id="acme")
        for uuid, email in ((ANA, "ana@example.com"), (BO, "bo@example.com"), (STAFF, "someone@posthog.com")):
            create_person(team=self.team, uuid=uuid, distinct_ids=[uuid], properties={"email": email})

    def _call(self, person: str, timestamp: str, group_key: str = "acme", **properties: Any) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id=person,
            person_id=person,
            timestamp=timestamp,
            properties={"$group_0": group_key, **properties},
        )

    def _run(self, **kwargs: Any) -> Any:
        flush_persons_and_events()
        query = AccountAgentActivityQuery(accountId=str(self.account.id), weeks=4, **kwargs)
        return AccountAgentActivityQueryRunner(team=self.team, query=query, user=self.user).calculate().results

    def test_summarises_what_agents_did_for_the_account_only(self) -> None:
        sql = {"$mcp_tool_name": "exec", "$mcp_exec_target_tool": "execute-sql"}
        self._call(
            ANA,
            "2026-10-27T10:00:00Z",
            **sql,
            **{
                "$mcp_conversation_id": "c1",
                "$mcp_client_name": "Example IDE",
                "$mcp_intent": "Find accounts that stopped using dashboards",
            },
        )
        self._call(
            ANA,
            "2026-10-27T10:05:00Z",
            **sql,
            **{
                "$mcp_conversation_id": "c1",
                "$mcp_client_name": "Example IDE",
                "$mcp_intent": "Find accounts that stopped using dashboards",
                "$mcp_is_error": True,
            },
        )
        self._call(
            ANA,
            "2026-10-20T09:00:00Z",
            **{"$mcp_tool_name": "insight-get", "$mcp_conversation_id": "c2", "$mcp_client_name": "Example IDE"},
        )
        self._call(
            BO,
            "2026-10-26T11:00:00Z",
            **{
                "$mcp_tool_name": "create-feature-flag",
                "$mcp_conversation_id": "c3",
                "$mcp_client_name": "Example Agent",
                "$mcp_intent": "Roll out the new onboarding flag",
            },
        )
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=BO,
            person_id=BO,
            timestamp="2026-10-26T12:00:00Z",
            properties={"$group_0": "acme"},
        )
        self._call(BO, "2026-10-26T11:00:00Z", group_key="other", **{"$mcp_tool_name": "survey-delete"})
        self._call(STAFF, "2026-10-26T11:00:00Z", **{"$mcp_tool_name": "survey-delete"})
        self._call(ANA, "2026-08-01T11:00:00Z", **{"$mcp_tool_name": "survey-delete"})

        results = self._run()

        assert results.emptyReason is None
        totals = results.totals
        assert (totals.agentCalls, totals.agentPeople, totals.conversations, totals.errors) == (4, 2, 3, 1)
        assert (totals.reads, totals.writes, totals.uiPageviews) == (3, 1, 1)
        assert [(t.product, t.tool, t.access, t.calls, t.people, t.conversations, t.errors) for t in results.tools] == [
            ("dwh", "execute-sql", "read", 2, 1, 1, 1),
            ("flags", "create-feature-flag", "write", 1, 1, 1, 0),
            ("pa", "insight-get", "read", 1, 1, 1, 0),
        ]
        assert [(c.name, c.calls, c.people) for c in results.clients] == [
            ("Example IDE", 3, 1),
            ("Example Agent", 1, 1),
        ]
        assert [(i.intent, i.calls, i.conversations) for i in results.intents] == [
            ("Find accounts that stopped using dashboards", 2, 1),
            ("Roll out the new onboarding flag", 1, 1),
        ]
        assert [(b.agentCalls, b.uiPageviews) for b in results.buckets][-2:] == [(1, 0), (3, 1)]

    def test_reports_an_account_without_an_external_id(self) -> None:
        self.account = create_account(team_id=self.team.id, name="Unlinked", external_id=None)

        results = self._run()

        assert results.emptyReason == AccountActivityMatrixEmptyReason.NO_EXTERNAL_ID
        assert results.tools == [] and results.totals.agentCalls == 0

    def test_refuses_an_account_the_caller_cannot_see(self) -> None:
        self.organization.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL}]
        self.organization.save()
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(self.account.id),
            access_level="none",
            organization_member=OrganizationMembership.objects.get(user=self.user, organization=self.organization),
        )
        query = AccountAgentActivityQuery(accountId=str(self.account.id))

        with pytest.raises(UserAccessControlError):
            AccountAgentActivityQueryRunner(team=self.team, query=query, user=self.user).validate_query_runner_access(
                self.user
            )

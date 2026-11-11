from typing import Any

import pytest
import time_machine
from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from rest_framework.exceptions import ValidationError

from posthog.schema import AccountTopPagesQuery

from posthog.test.persons import create_person

from products.customer_analytics.backend.hogql_queries.account_top_pages_query_runner import AccountTopPagesQueryRunner
from products.customer_analytics.backend.test.factories import create_account

ANA = "11111111-1111-4111-8111-111111111111"
BO = "22222222-2222-4222-8222-222222222222"
STAFF = "33333333-3333-4333-8333-333333333333"


@time_machine.travel("2026-10-28T18:00:00Z", tick=False)
class TestAccountTopPagesQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save()
        self.account = create_account(team_id=self.team.id, external_id="acme")
        for uuid, email in ((ANA, "ana@example.com"), (BO, "bo@example.com"), (STAFF, "someone@posthog.com")):
            create_person(team=self.team, uuid=uuid, distinct_ids=[uuid], properties={"email": email})

    def _view(self, person: str, path: str, timestamp: str, title: str | None = None, group_key: str = "acme") -> None:
        _create_event(
            team=self.team,
            event="$pageview",
            distinct_id=person,
            person_id=person,
            timestamp=timestamp,
            properties={"$group_0": group_key, "$pathname": path, **({"title": title} if title else {})},
        )

    def _run(self, **kwargs: Any) -> Any:
        flush_persons_and_events()
        query = AccountTopPagesQuery(accountId=str(self.account.id), weeks=4, **kwargs)
        return AccountTopPagesQueryRunner(team=self.team, query=query, user=self.user).calculate().results

    def test_ranks_the_account_pages_across_projects_with_their_latest_title(self) -> None:
        self._view(ANA, "/project/7/dashboard/12", "2026-10-20T10:00:00Z", "Weekly metrics")
        self._view(BO, "/project/9/dashboard/12", "2026-10-27T10:00:00Z", "Weekly metrics v2")
        self._view(ANA, "/project/7/dashboard/12", "2026-10-27T11:00:00Z", "Weekly metrics v2")
        self._view(ANA, "/project/7/insights/AbC1", "2026-10-27T12:00:00Z", "Signups by plan")
        self._view(ANA, "/project/7/some-new-area", "2026-10-27T12:00:00Z")
        self._view(BO, "/project/7/surveys", "2026-10-27T12:00:00Z", group_key="other")
        self._view(STAFF, "/project/7/surveys", "2026-10-27T12:00:00Z")
        self._view(ANA, "/project/7/surveys", "2026-08-01T12:00:00Z")

        results = self._run()

        assert [(p.path, p.title, p.product, p.views, p.people, p.activeDays) for p in results.pages] == [
            ("/dashboard/12", "Weekly metrics v2", "pa", 3, 2, 2),
            ("/insights/AbC1", "Signups by plan", "pa", 1, 1, 1),
            ("/some-new-area", "", "", 1, 1, 1),
        ]

    def test_filters_to_one_product_and_refuses_an_unknown_one(self) -> None:
        self._view(ANA, "/project/7/dashboard/12", "2026-10-27T10:00:00Z")
        self._view(ANA, "/project/7/feature_flags/3", "2026-10-27T10:00:00Z", "Onboarding flag")

        assert [p.path for p in self._run(productKey="flags").pages] == ["/feature_flags/3"]
        with pytest.raises(ValidationError):
            self._run(productKey="not-a-product")

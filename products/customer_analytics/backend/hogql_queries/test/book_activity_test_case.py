from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from posthog.models import User
from posthog.test.persons import create_person

from products.customer_analytics.backend.constants import CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG
from products.customer_analytics.backend.models import Account
from products.customer_analytics.backend.test.factories import create_account

ANA = "11111111-1111-4111-8111-111111111111"
BO = "22222222-2222-4222-8222-222222222222"
CY = "33333333-3333-4333-8333-333333333333"
DEE = "44444444-4444-4444-8444-444444444444"
EVE = "55555555-5555-4555-8555-555555555555"


class BookActivityTestCase(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.flag_enabled = True
        flag_patch = patch(
            "posthog.permissions.posthoganalytics.feature_enabled",
            side_effect=lambda flag, *_args, **_kwargs: (
                self.flag_enabled and flag == CUSTOMER_ANALYTICS_PRODUCT_USAGE_FLAG
            ),
        )
        flag_patch.start()
        self.addCleanup(flag_patch.stop)
        self.team.customer_analytics_config.account_group_type_index = 0
        self.team.customer_analytics_config.save()
        self.other_user = User.objects.create_and_join(self.organization, "other@example.com", "password")
        self.alpha = create_account(team_id=self.team.id, name="Alpha", external_id="org-a")
        self.beta = create_account(team_id=self.team.id, name="Beta", external_id="org-b")
        for person in (ANA, BO, CY, DEE, EVE):
            create_person(team=self.team, uuid=person, distinct_ids=[person], properties={})

    def _event(
        self,
        person: str,
        event: str,
        timestamp: str,
        account: Account,
        properties: dict[str, Any] | None = None,
        person_properties: dict[str, Any] | None = None,
        group_type_index: int = 0,
    ) -> None:
        _create_event(
            team=self.team,
            event=event,
            distinct_id=person,
            person_id=person,
            timestamp=timestamp,
            properties={f"$group_{group_type_index}": account.external_id, **(properties or {})},
            person_properties={"email": f"{person[:3]}@example.com"}
            if person_properties is None
            else person_properties,
        )

    def _dwell(
        self,
        person: str,
        seconds: float,
        timestamp: str,
        account: Account,
        path: str = "/project/1/insights/a",
        event: str = "$pageview",
    ) -> None:
        self._event(
            person,
            event,
            timestamp,
            account,
            properties={"$prev_pageview_pathname": path, "$prev_pageview_duration": seconds},
        )

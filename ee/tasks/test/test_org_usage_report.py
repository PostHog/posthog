from typing import Union
from uuid import uuid4

from django.utils.timezone import datetime
from freezegun.api import freeze_time

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.group import create_group
from ee.clickhouse.util import ClickhouseTestMixin
from ee.tasks.org_usage_report import send_all_org_usage_reports
from posthog.constants import AnalyticsDBMS
from posthog.models import GroupTypeMapping, Person, Team
from posthog.tasks.test.test_org_usage_report import factory_org_usage_report


def create_person(distinct_id: str, team: Team) -> Person:
    return Person.objects.create(team=team, distinct_ids=[distinct_id])


def create_event_clickhouse(
    distinct_id: str, event: str, lib: str, timestamp: Union[datetime, str], team: Team, properties={}
) -> None:
    create_event(
        event_uuid=uuid4(),
        team=team,
        distinct_id=distinct_id,
        event=event,
        timestamp=timestamp,
        properties={"$lib": lib, **properties},
    )


class TestOrganizationUsageReport(ClickhouseTestMixin, factory_org_usage_report(create_person, create_event_clickhouse, send_all_org_usage_reports, {"USE_TZ": False, "PRIMARY_DB": AnalyticsDBMS.CLICKHOUSE})):  # type: ignore
    def test_groups_usage(self):
        GroupTypeMapping.objects.create(team=self.team, group_type="organization", group_type_index=0)
        GroupTypeMapping.objects.create(team=self.team, group_type="company", group_type_index=1)
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:5", properties={"industry": "finance"})
        create_group(team_id=self.team.pk, group_type_index=0, group_key="org:6", properties={"industry": "technology"})

        with freeze_time("2021-11-11 00:30:00"):
            create_event_clickhouse(
                event="event",
                lib="web",
                distinct_id="user_1",
                team=self.team,
                timestamp="2021-11-10 02:00:00",
                properties={"$group_0": "org:5"},
            )
            create_event_clickhouse(
                event="event",
                lib="web",
                distinct_id="user_1",
                team=self.team,
                timestamp="2021-11-10 05:00:00",
                properties={"$group_0": "org:6"},
            )

            create_event_clickhouse(
                event="event", lib="web", distinct_id="user_7", team=self.team, timestamp="2021-11-10 10:00:00",
            )

            all_reports = send_all_org_usage_reports(dry_run=True)
            org_report = self.select_report_by_org_id(str(self.organization.id), all_reports)

            self.assertEqual(org_report["group_types_total"], 2)
            self.assertEqual(org_report["event_count_in_month"], 3)
            self.assertEqual(org_report["event_count_with_groups_month"], 2)

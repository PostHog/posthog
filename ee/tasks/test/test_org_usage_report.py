from uuid import uuid4

from django.utils.timezone import datetime

from ee.clickhouse.models.event import create_event
from ee.clickhouse.models.session_recording_event import create_session_recording_event
from ee.tasks.org_usage_report import send_all_org_usage_reports
from posthog.constants import AnalyticsDBMS
from posthog.models import Person, Team
from posthog.tasks.test.test_org_usage_report import factory_org_usage_report


def create_person(distinct_id: str, team: Team) -> Person:
    return Person.objects.create(team=team, distinct_ids=[distinct_id])


def create_event_clickhouse(distinct_id: str, event: str, lib: str, created_at: datetime, team: Team) -> None:
    create_event(
        event_uuid=uuid4(),
        team=team,
        distinct_id=distinct_id,
        event=event,
        timestamp=created_at,
        properties={"$lib": lib},
    )


def create_session_recording_clickhouse(distinct_id: str, created_at: datetime, team: Team, session_id: str) -> None:
    create_session_recording_event(
        uuid=uuid4(),
        team_id=team.id,
        distinct_id=distinct_id,
        session_id=session_id,
        window_id=str(uuid4()),
        timestamp=created_at,
        snapshot_data={},
    )


class TestOrganizationUsageReport(factory_org_usage_report(create_person, create_event_clickhouse, create_session_recording_clickhouse, send_all_org_usage_reports, {"EE_AVAILABLE": True, "USE_TZ": False, "PRIMARY_DB": AnalyticsDBMS.CLICKHOUSE})):  # type: ignore
    pass

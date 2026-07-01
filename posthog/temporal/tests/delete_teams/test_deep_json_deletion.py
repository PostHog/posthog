import pytest

from django.db import connection

from asgiref.sync import sync_to_async

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.util import delete_team_records

from products.cohorts.backend.models.cohort import Cohort

pytestmark = [pytest.mark.django_db(transaction=True)]

# Deep enough that Python's C json scanner overflows decoding it (~9999), but shallow enough
# that Postgres can still parse it into jsonb once max_stack_depth is raised for the write.
# In production the same asymmetry holds: the DB stored it, the worker's json.loads can't read it.
_NESTING_DEPTH = 12_000


def _bootstrap_team() -> int:
    _, _, team = Organization.objects.bootstrap(None)
    return team.id


def _write_deeply_nested_cohort(team_id: int) -> int:
    """Create a cohort whose `query` jsonb is nested past json.loads' recursion ceiling.

    Built as text and cast in Postgres so no Python json encode happens on the way in — the
    cascade delete's row materialization is the first thing that tries to decode it. Postgres'
    JSON *parser* is recursive too, so the write needs a raised max_stack_depth; reading the
    value back out is iterative and works at the default depth (as it does in production).
    """
    cohort = Cohort.objects.create(team_id=team_id, name="deep")
    with connection.cursor() as cursor:
        cursor.execute("SET max_stack_depth = '7000kB'")
        cursor.execute(
            "UPDATE posthog_cohort SET query = (repeat('[', %s) || repeat(']', %s))::jsonb WHERE id = %s",
            [_NESTING_DEPTH, _NESTING_DEPTH, cohort.id],
        )
    return cohort.id


def test_reading_the_deep_cohort_raises_recursion_error():
    """Sanity check: the fixture really does produce an undecodable row."""
    team_id = _bootstrap_team()
    cohort_id = _write_deeply_nested_cohort(team_id)
    with pytest.raises(RecursionError):
        # Materializing the row decodes `query` via json.loads → overflow.
        _ = Cohort.objects.get(id=cohort_id).query


async def test_delete_team_records_survives_deeply_nested_json():
    team_id = await sync_to_async(_bootstrap_team)()
    await sync_to_async(_write_deeply_nested_cohort)(team_id)

    await sync_to_async(delete_team_records)([team_id])

    assert not await sync_to_async(Team.objects.filter(id=team_id).exists)()

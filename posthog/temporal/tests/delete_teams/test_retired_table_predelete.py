import pytest

from django.db import connection

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.team.util import _delete_misc_small_tables_for_teams, delete_team_records

# transaction=True is required, not incidental: the foreign key this table holds on posthog_team
# is DEFERRABLE INITIALLY DEFERRED, so Postgres only checks it at COMMIT. Under a plain TestCase
# the inner atomic() is a savepoint, releasing it never checks it, and the regression is invisible.
pytestmark = [pytest.mark.django_db(transaction=True)]

_ROW_INSERT = (
    "INSERT INTO ee_single_session_summary "
    "(id, created_at, team_id, session_id, summary, exception_event_ids) "
    "VALUES (gen_random_uuid(), now(), %s, 'session-1', '{}'::jsonb, ARRAY['event-1'])"
)


def test_team_deletion_clears_rows_in_retired_session_summary_table():
    _, _, team = Organization.objects.bootstrap(None)
    team_id = team.id
    with connection.cursor() as cursor:
        cursor.execute(_ROW_INSERT, [team_id])

    _delete_misc_small_tables_for_teams([team_id])
    delete_team_records([team_id])

    assert not Team.objects.filter(id=team_id).exists()

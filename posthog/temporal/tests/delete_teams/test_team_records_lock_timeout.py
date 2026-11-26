import pytest

from django.db import OperationalError, connections

from posthog.models.organization import Organization
from posthog.models.team import (
    Team,
    util as team_util,
)

# The holding session must see the committed team row, which the rollback-based TestCase never commits.
pytestmark = [pytest.mark.django_db(transaction=True)]


@pytest.mark.timeout(60)
def test_a_retry_fails_fast_behind_a_transaction_that_holds_the_team_row(monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, team = Organization.objects.bootstrap(None)
    monkeypatch.setattr(team_util, "TEAM_RECORDS_LOCK_TIMEOUT_MS", 200)
    holder = connections.create_connection("default")
    try:
        holder.set_autocommit(False)
        with holder.cursor() as cursor:
            cursor.execute("SELECT id FROM posthog_team WHERE id = %s FOR UPDATE", [team.id])

        with pytest.raises(OperationalError, match="lock timeout"):
            team_util.delete_team_records([team.id])
    finally:
        holder.rollback()
        holder.close()

    assert Team.objects.filter(id=team.id).exists()

from __future__ import annotations

import random
import datetime as dt

import pytest
from unittest.mock import patch

from django.db import ProgrammingError

import psycopg.errors
from asgiref.sync import async_to_sync
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team

from products.alerts.backend.facade.contracts import PlatformAlertOutcome, SourceOutcomeInputs
from products.alerts.backend.temporal.outcomes import WRITE_PERMISSION_DENIED, alerts_product_record_outcomes_activity


def _inputs(team_id: int) -> SourceOutcomeInputs:
    return SourceOutcomeInputs(
        team_id=team_id,
        cutoff=dt.datetime(2026, 9, 22, 10, tzinfo=dt.UTC).isoformat(),
        outcomes=[
            PlatformAlertOutcome(
                configuration_id="01997d4a-0000-0000-0000-000000000000",
                new_state="firing",
                notified=True,
                consecutive_failures=0,
            )
        ],
    )


def _database_error(cause: Exception) -> ProgrammingError:
    error = ProgrammingError("permission denied")
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    "cause,non_retryable",
    [
        (psycopg.errors.InsufficientPrivilege("permission denied"), True),
        (psycopg.errors.UndefinedTable("relation does not exist"), False),
    ],
)
@pytest.mark.django_db(transaction=True)
def test_only_a_privilege_error_stops_the_write_retrying(cause: Exception, non_retryable: bool) -> None:
    organization = Organization.objects.create(name=f"AlertsOutcomesOrg-{random.randint(1, 99999)}")
    team = Team.objects.create(organization=organization, name="AlertsOutcomesTeam")
    failure = _database_error(cause)

    with patch("products.alerts.backend.facade.platform_alerts.record_outcomes", side_effect=failure):
        run = async_to_sync(ActivityEnvironment().run)
        if non_retryable:
            with pytest.raises(ApplicationError) as caught:
                run(alerts_product_record_outcomes_activity, _inputs(team.id))
            assert caught.value.type == WRITE_PERMISSION_DENIED
            assert caught.value.non_retryable
            # The role and the table it could not write are deployment facts, not batch data.
            assert "permission denied" not in caught.value.message
        else:
            with pytest.raises(ProgrammingError) as caught_unrelated:
                run(alerts_product_record_outcomes_activity, _inputs(team.id))
            assert caught_unrelated.value is failure

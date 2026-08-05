import pytest

from dagster import build_op_context

from posthog.dags.backfill_internal_test_users_cohort import (
    _INTERNAL_TEST_USERS_FILTERS,
    create_internal_test_users_cohorts_op,
)
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.cohorts.backend.models.cohort import Cohort, CohortKind


@pytest.mark.django_db
def test_create_internal_test_users_cohorts_op_sets_condition_type_on_bulk_created_rows():
    org = Organization.objects.create(name="test-org-internal-test-users")
    team = Team.objects.create(organization=org, name="test-team-internal-test-users")

    create_internal_test_users_cohorts_op(build_op_context(), [team.id])

    cohort = Cohort.objects.get(team=team, kind=CohortKind.INTERNAL_TEST_USERS)
    assert cohort.condition_type == Cohort.compute_condition_type(_INTERNAL_TEST_USERS_FILTERS)

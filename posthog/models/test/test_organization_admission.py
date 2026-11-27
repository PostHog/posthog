import uuid

import pytest

from django.db import OperationalError, connections

from posthog.models import Organization, Team
from posthog.models.organization_admission import Admission, AdmissionSnapshotMissing, OrganizationAdmission


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


class PrimaryFault:
    def __init__(self, failures: int) -> None:
        self.failures = failures

    def __call__(self, execute, sql, params, many, context):
        if self.failures > 0:
            self.failures -= 1
            raise OperationalError("primary is down")
        return execute(sql, params, many, context)


def _team_in_organization(is_active: bool | None) -> Team:
    organization = Organization.objects.create(name="Admission test org", is_active=is_active)
    return Team.objects.create(organization=organization, name="Admission test team")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "is_active,expected",
    [
        (True, Admission.ADMITTED),
        (None, Admission.ADMITTED),
        (False, Admission.DEACTIVATED),
    ],
)
def test_admission_by_team_and_organization(is_active: bool | None, expected: Admission) -> None:
    team = _team_in_organization(is_active)
    admission = OrganizationAdmission(clock=FakeClock())

    assert admission.check(team_id=team.id) == expected
    assert admission.check(organization_id=team.organization_id) == expected
    assert admission.check(organization_id=str(team.organization_id)) == expected


@pytest.mark.django_db
@pytest.mark.parametrize(
    "tenant,expected",
    [
        ({}, Admission.UNRESOLVED),
        ({"team_id": 0}, Admission.UNRESOLVED),
        ({"organization_id": "not-a-uuid"}, Admission.UNRESOLVED),
        ({"team_id": 987_654_321}, Admission.ADMITTED),
        ({"organization_id": uuid.uuid4()}, Admission.ADMITTED),
    ],
)
def test_tenant_outside_the_deactivated_set(tenant: dict, expected: Admission) -> None:
    _team_in_organization(is_active=False)
    admission = OrganizationAdmission(clock=FakeClock())

    assert admission.check(**tenant) == expected


@pytest.mark.django_db
def test_deactivation_takes_effect_at_the_next_refresh(django_assert_num_queries) -> None:
    team = _team_in_organization(is_active=True)
    clock = FakeClock()
    admission = OrganizationAdmission(clock=clock)
    assert admission.check(team_id=team.id) == Admission.ADMITTED

    Organization.objects.filter(id=team.organization_id).update(is_active=False)
    clock.now += 29
    with django_assert_num_queries(0):
        assert admission.check(team_id=team.id) == Admission.ADMITTED
        assert admission.check(team_id=987_654_321) == Admission.ADMITTED

    clock.now += 1
    assert admission.check(team_id=team.id) == Admission.DEACTIVATED


@pytest.mark.django_db
def test_reads_the_replica_when_the_primary_fails() -> None:
    team = _team_in_organization(is_active=False)
    admission = OrganizationAdmission(clock=FakeClock(), replica="default")

    with connections["default"].execute_wrapper(PrimaryFault(failures=1)):
        assert admission.check(team_id=team.id) == Admission.DEACTIVATED


@pytest.mark.django_db
def test_raises_when_primary_and_replica_fail_and_waits_before_retrying(django_assert_num_queries) -> None:
    team = _team_in_organization(is_active=False)
    clock = FakeClock()
    admission = OrganizationAdmission(clock=clock, replica="default")

    with connections["default"].execute_wrapper(PrimaryFault(failures=2)):
        with pytest.raises(OperationalError):
            admission.check(team_id=team.id)

    clock.now += 29
    with django_assert_num_queries(0), pytest.raises(AdmissionSnapshotMissing):
        admission.check(team_id=team.id)

    clock.now += 1
    assert admission.check(team_id=team.id) == Admission.DEACTIVATED

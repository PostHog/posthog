import time
import uuid
import threading
from collections.abc import Callable
from enum import StrEnum
from typing import TypeVar

from django.conf import settings
from django.db import DatabaseError

from posthog.dataclasses import frozen
from posthog.models.organization import Organization
from posthog.models.team.team import Team

REFRESH_INTERVAL_SECONDS = 30.0

_Read = TypeVar("_Read")


class Admission(StrEnum):
    ADMITTED = "admitted"
    DEACTIVATED = "deactivated"
    UNRESOLVED = "unresolved"


@frozen
class _DeactivatedTenants:
    organization_ids: frozenset[uuid.UUID]
    team_ids: frozenset[int]
    loaded_at: float


class OrganizationAdmission:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        primary: str = "default",
        replica: str = "replica",
    ) -> None:
        self._clock = clock
        self._primary = primary
        self._replica = replica
        self._lock = threading.Lock()
        self._deactivated: _DeactivatedTenants | None = None
        self._existing_teams: dict[int, bool] = {}
        self._existing_organizations: dict[uuid.UUID, bool] = {}

    def check(self, *, team_id: int | None = None, organization_id: uuid.UUID | str | None = None) -> Admission:
        if team_id:
            return self._check_team(team_id)
        parsed_organization_id = _parse_uuid(organization_id)
        if parsed_organization_id:
            return self._check_organization(parsed_organization_id)
        return Admission.UNRESOLVED

    def _check_team(self, team_id: int) -> Admission:
        with self._lock:
            deactivated = self._current_deactivated()
            if team_id in deactivated.team_ids:
                return Admission.DEACTIVATED
            if team_id not in self._existing_teams:
                self._existing_teams[team_id] = self._read(
                    lambda database: Team.objects.using(database).filter(id=team_id).exists()
                )
            return Admission.ADMITTED if self._existing_teams[team_id] else Admission.UNRESOLVED

    def _check_organization(self, organization_id: uuid.UUID) -> Admission:
        with self._lock:
            deactivated = self._current_deactivated()
            if organization_id in deactivated.organization_ids:
                return Admission.DEACTIVATED
            if organization_id not in self._existing_organizations:
                self._existing_organizations[organization_id] = self._read(
                    lambda database: Organization.objects.using(database).filter(id=organization_id).exists()
                )
            return Admission.ADMITTED if self._existing_organizations[organization_id] else Admission.UNRESOLVED

    def _current_deactivated(self) -> _DeactivatedTenants:
        now = self._clock()
        if self._deactivated is None or now - self._deactivated.loaded_at >= REFRESH_INTERVAL_SECONDS:
            organization_ids, team_ids = self._read(_load_deactivated)
            self._deactivated = _DeactivatedTenants(organization_ids=organization_ids, team_ids=team_ids, loaded_at=now)
            self._existing_teams.clear()
            self._existing_organizations.clear()
        return self._deactivated

    def _read(self, query: Callable[[str], _Read]) -> _Read:
        try:
            return query(self._primary)
        except DatabaseError:
            if self._replica not in settings.DATABASES:
                raise
            return query(self._replica)


def _load_deactivated(database: str) -> tuple[frozenset[uuid.UUID], frozenset[int]]:
    organization_ids = frozenset(
        Organization.objects.using(database).filter(is_active=False).values_list("id", flat=True)
    )
    if not organization_ids:
        return organization_ids, frozenset()
    team_ids = frozenset(
        Team.objects.using(database).filter(organization_id__in=organization_ids).values_list("id", flat=True)
    )
    return organization_ids, team_ids


def _parse_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


ORGANIZATION_ADMISSION = OrganizationAdmission()


def organization_deactivated(
    *, team_id: int | None = None, organization_id: uuid.UUID | str | None = None
) -> Admission:
    return ORGANIZATION_ADMISSION.check(team_id=team_id, organization_id=organization_id)

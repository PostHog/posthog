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


class AdmissionSnapshotMissing(Exception):
    pass


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
        self._refresh_lock = threading.Lock()
        self._deactivated: _DeactivatedTenants | None = None
        self._last_attempt: float | None = None

    def check(self, *, team_id: int | None = None, organization_id: uuid.UUID | str | None = None) -> Admission:
        self.refresh_if_stale()
        return self.check_cached(team_id=team_id, organization_id=organization_id)

    def check_cached(self, *, team_id: int | None = None, organization_id: uuid.UUID | str | None = None) -> Admission:
        parsed_organization_id = _parse_uuid(organization_id)
        if not team_id and not parsed_organization_id:
            return Admission.UNRESOLVED
        deactivated = self._deactivated
        if deactivated is None:
            raise AdmissionSnapshotMissing()
        if team_id:
            return Admission.DEACTIVATED if team_id in deactivated.team_ids else Admission.ADMITTED
        return Admission.DEACTIVATED if parsed_organization_id in deactivated.organization_ids else Admission.ADMITTED

    def has_snapshot(self) -> bool:
        return self._deactivated is not None

    def is_stale(self) -> bool:
        last_attempt = self._last_attempt
        return last_attempt is None or self._clock() - last_attempt >= REFRESH_INTERVAL_SECONDS

    def refresh_if_stale(self) -> None:
        if not self.is_stale():
            return
        if not self._refresh_lock.acquire(blocking=self._deactivated is None):
            return
        try:
            if not self.is_stale():
                return
            self._last_attempt = self._clock()
            organization_ids, team_ids = self._read(_load_deactivated)
            self._deactivated = _DeactivatedTenants(organization_ids=organization_ids, team_ids=team_ids)
        finally:
            self._refresh_lock.release()

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

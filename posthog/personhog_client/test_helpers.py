"""Shared test helpers for personhog tests.

Provides PersonhogTestMixin with helper methods for tests that exercise
personhog-backed reads.  The global conftest fixture activates the fake for
every test, so the mixin no longer manages its own client lifecycle.
"""

from __future__ import annotations

from typing import Any

from posthog.models.person import Person
from posthog.personhog_client.fake_client import FakePersonHogClient


class PersonhogTestMixin:
    """Mixin providing convenience helpers for tests that exercise personhog reads.

    The global ``_activate_personhog_fake`` conftest fixture activates the fake
    for every test.  This mixin exposes ``_fake_client`` pointing at that global
    fake, plus ``_seed_person``, ``_assert_personhog_called``, etc.
    """

    _fake_client: FakePersonHogClient | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        from posthog.personhog_client.fake_client import get_active_fake

        self._fake_client = get_active_fake()

    def _seed_person(
        self,
        *,
        team: Any,
        distinct_ids: list[str],
        properties: dict | None = None,
        **_fake_overrides: Any,
    ) -> Person:
        from posthog.test.persons import create_person

        return create_person(
            team=team,
            distinct_ids=distinct_ids,
            properties=properties or {},
        )

    def _seed_cohort_membership(self, *, person_id: int, cohort_id: int, is_member: bool = True) -> None:
        """Seed a cohort membership in the fake personhog client."""
        if self._fake_client is not None:
            self._fake_client.add_cohort_membership(person_id=person_id, cohort_id=cohort_id, is_member=is_member)

    def _assert_personhog_called(self, method: str, *, times: int | None = None) -> list[Any]:
        """Assert a personhog method was called.  Returns matched calls for inspection."""
        if self._fake_client is not None:
            return self._fake_client.assert_called(method, times=times)
        return []

    def _assert_personhog_not_called(self, method: str) -> None:
        """Assert a personhog method was NOT called."""
        if self._fake_client is not None:
            self._fake_client.assert_not_called(method)

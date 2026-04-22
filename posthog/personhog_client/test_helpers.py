"""Shared test helpers for personhog parameterized tests.

Provides PersonhogTestMixin for use with @parameterized_class to run
integration tests against both ORM and personhog paths.

Usage::

    from parameterized import parameterized_class
    from posthog.personhog_client.test_helpers import PersonhogTestMixin

    @parameterized_class(("personhog",), [(False,), (True,)])
    class TestMyFeature(PersonhogTestMixin, BaseTest):
        def test_something(self):
            person = self._seed_person(
                team=self.team,
                distinct_ids=["user-1"],
                properties={"email": "test@example.com"},
            )
            # ... exercise the code path ...
            self._assert_personhog_called("get_person_by_distinct_id")
"""

from __future__ import annotations

from typing import Any

from posthog.models.person import Person
from posthog.personhog_client.fake_client import FakePersonHogClient, fake_personhog_client


class PersonhogTestMixin:
    """Mixin for ``@parameterized_class`` tests that run against both ORM and personhog.

    Expects ``self.personhog: bool`` to be set by ``@parameterized_class``.

    * ``setUp`` conditionally activates ``fake_personhog_client()``
    * ``_seed_person`` always creates a real DB ``Person`` **and**, when
      personhog is active, registers it in the fake client
    * ``_assert_personhog_called`` / ``_assert_personhog_not_called`` are
      no-ops on the ORM path so assertions can be shared across both runs
    """

    personhog: bool = False
    _personhog_cm: Any = None
    _fake_client: FakePersonHogClient | None = None

    def setUp(self) -> None:
        super().setUp()  # type: ignore[misc]
        if self.personhog:
            self._personhog_cm = fake_personhog_client()
            self._fake_client = self._personhog_cm.__enter__()
        else:
            self._personhog_cm = None
            self._fake_client = None

    def tearDown(self) -> None:
        if self._personhog_cm is not None:
            self._personhog_cm.__exit__(None, None, None)
        super().tearDown()  # type: ignore[misc]

    def _seed_person(
        self,
        *,
        team: Any,
        distinct_ids: list[str],
        properties: dict | None = None,
        **fake_overrides: Any,
    ) -> Person:
        """Create a person in the DB and optionally seed the fake personhog client.

        Always creates a real DB record (needed for the ORM path and any
        secondary queries like ClickHouse joins).  When ``self.personhog``
        is ``True``, additionally registers the person in the fake client.

        Extra keyword arguments are forwarded to
        ``FakePersonHogClient.add_person()`` and override the defaults
        derived from the DB record.
        """
        person = Person.objects.create(
            team=team,
            distinct_ids=distinct_ids,
            properties=properties or {},
        )
        if self._fake_client is not None:
            fake_kwargs: dict[str, Any] = {
                "is_identified": person.is_identified,
                "created_at": int(person.created_at.timestamp() * 1000) if person.created_at else 0,
            }
            fake_kwargs.update(fake_overrides)
            self._fake_client.add_person(
                team_id=team.pk,
                person_id=person.pk,
                uuid=str(person.uuid),
                distinct_ids=distinct_ids,
                properties=properties,
                **fake_kwargs,
            )
        return person

    def _assert_personhog_called(self, method: str, *, times: int | None = None) -> list[Any]:
        """Assert a personhog method was called.  No-op on the ORM path.

        Returns the matched calls so tests can inspect request arguments.
        """
        if self._fake_client is not None:
            return self._fake_client.assert_called(method, times=times)
        return []

    def _assert_personhog_not_called(self, method: str) -> None:
        """Assert a personhog method was NOT called.  No-op on the ORM path."""
        if self._fake_client is not None:
            self._fake_client.assert_not_called(method)

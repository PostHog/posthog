from __future__ import annotations

from contextlib import nullcontext

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError

import psycopg

from posthog.persons_db import persons_db_connection

from products.cohorts.backend.models.cohort import Cohort

pytestmark = [pytest.mark.django_db, pytest.mark.persons_db_direct]

UNIQUE_INDEX = "posthog_cohortpeople_cohort_id_person_id_uniq"
DROP_UNIQUE_INDEX = f"DROP INDEX IF EXISTS {UNIQUE_INDEX}"
CREATE_UNIQUE_INDEX = f"CREATE UNIQUE INDEX {UNIQUE_INDEX} ON posthog_cohortpeople (cohort_id, person_id)"


@pytest.fixture
def persons_conn():
    """A persons connection with no unique (cohort_id, person_id) index, and the seeded rows gone.

    The index rejects the surplus rows this command exists to remove, so it has to go before a
    test can seed them. Whether this schema declares the index at all depends on how far its
    out-of-band build has reached, so the fixture restores it only if it found it.
    """
    with persons_db_connection(writer=True, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", (UNIQUE_INDEX,))
            declared = cur.fetchone()[0]
            cur.execute(DROP_UNIQUE_INDEX)
        yield conn
        with conn.cursor() as cur:
            cur.execute("DELETE FROM posthog_cohortpeople")
            if declared:
                cur.execute(CREATE_UNIQUE_INDEX)


def _add_member(conn: psycopg.Connection, cohort_id: int, person_id: int, version: int | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO posthog_cohortpeople (cohort_id, person_id, version) VALUES (%s, %s, %s)",
            (cohort_id, person_id, version),
        )


def _members(conn: psycopg.Connection, cohort_id: int) -> list[tuple[int, int | None]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT person_id, version FROM posthog_cohortpeople WHERE cohort_id = %s ORDER BY person_id",
            (cohort_id,),
        )
        return cur.fetchall()


def test_repair_keeps_one_row_per_person_at_the_highest_version(persons_conn):
    for person_id, version in [(11, 1), (11, None), (11, 3), (12, 2), (13, 1), (13, 1)]:
        _add_member(persons_conn, 900, person_id, version)
    _add_member(persons_conn, 901, 11, 1)

    call_command("cohortpeople_dedup", "--mode", "repair")

    assert _members(persons_conn, 900) == [(11, 3), (12, 2), (13, 1)]
    assert _members(persons_conn, 901) == [(11, 1)]
    # The sweep exists to let the unique index build, so build it.
    with persons_conn.cursor() as cur:
        cur.execute(CREATE_UNIQUE_INDEX)
        cur.execute(DROP_UNIQUE_INDEX)


@pytest.mark.parametrize("versions,gated", [([1, 2], True), ([1], False)])
def test_verify_gates_on_surplus_rows_without_changing_them(persons_conn, versions, gated):
    for version in versions:
        _add_member(persons_conn, 900, 11, version)

    with pytest.raises(CommandError) if gated else nullcontext():
        call_command("cohortpeople_dedup", "--mode", "verify")

    assert _members(persons_conn, 900) == [(11, version) for version in versions]


@pytest.mark.parametrize(
    "is_static,expected_count",
    # A dynamic cohort keeps the rows of the static cohort it once was, but its size comes from
    # ClickHouse, so the stored count of 3 has to survive the repair.
    [(True, 2), (False, 3)],
)
def test_repair_corrects_the_size_only_where_this_table_is_the_source(persons_conn, team, is_static, expected_count):
    cohort = Cohort.objects.create(team=team, name="members", is_static=is_static, count=3)
    for person_id, version in [(11, 1), (11, 2), (12, 1)]:
        _add_member(persons_conn, cohort.pk, person_id, version)

    call_command("cohortpeople_dedup", "--mode", "repair")

    assert _members(persons_conn, cohort.pk) == [(11, 2), (12, 1)]
    cohort.refresh_from_db()
    assert cohort.count == expected_count

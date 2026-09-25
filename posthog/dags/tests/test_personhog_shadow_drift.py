import uuid

import pytest

import psycopg2
import psycopg2.extras

from posthog.dags.personhog_shadow_drift import compute_shadow_drift
from posthog.persons_db import persons_db_url

TEAM_ID = 990000123
CREATED_AT = "2026-01-01T00:00:00+00:00"


def _insert_person(
    cursor, table: str, person_uuid: uuid.UUID, properties: dict, is_deleted: bool = False, version: int = 1
) -> int:
    cursor.execute(
        f"INSERT INTO {table} (created_at, properties, is_identified, uuid, version, team_id, is_deleted) "
        "VALUES (%s, %s, false, %s, %s, %s, %s) RETURNING id",
        (CREATED_AT, psycopg2.extras.Json(properties), str(person_uuid), version, TEAM_ID, is_deleted),
    )
    return cursor.fetchone()["id"]


@pytest.mark.persons_db_direct
@pytest.mark.django_db(transaction=True)
def test_compute_shadow_drift_counts_each_category() -> None:
    connection = psycopg2.connect(persons_db_url(writer=True), cursor_factory=psycopg2.extras.RealDictCursor)
    connection.autocommit = True
    matched = uuid.uuid4()
    legacy_only = uuid.uuid4()
    personhog_only = uuid.uuid4()
    props_differ = uuid.uuid4()
    tombstoned = uuid.uuid4()

    try:
        with connection.cursor() as cursor:
            legacy_matched = _insert_person(cursor, "posthog_person", matched, {"a": 1})
            _insert_person(cursor, "posthog_person", legacy_only, {})
            _insert_person(cursor, "posthog_person", props_differ, {"b": 1})

            ph_matched = _insert_person(cursor, "personhog_person_tmp", matched, {"a": 1}, version=2)
            _insert_person(cursor, "personhog_person_tmp", personhog_only, {})
            ph_props = _insert_person(cursor, "personhog_person_tmp", props_differ, {"b": 2})
            ph_tombstoned = _insert_person(cursor, "personhog_person_tmp", tombstoned, {}, is_deleted=True)

            cursor.execute(
                "INSERT INTO posthog_persondistinctid (distinct_id, version, person_id, team_id) VALUES "
                "('shadow-drift-did-1', 1, %s, %s), ('shadow-drift-did-2', 1, %s, %s)",
                (legacy_matched, TEAM_ID, legacy_matched, TEAM_ID),
            )
            cursor.execute(
                "INSERT INTO personhog_persondistinctid_tmp (distinct_id, version, person_id, team_id) VALUES "
                "('shadow-drift-did-1', 1, %s, %s), ('shadow-drift-did-2', 1, %s, %s), "
                "('shadow-drift-did-3', 1, %s, %s)",
                (ph_matched, TEAM_ID, ph_props, TEAM_ID, ph_tombstoned, TEAM_ID),
            )

            cursor.execute(
                "INSERT INTO posthog_featureflaghashkeyoverride (feature_flag_key, hash_key, person_id, team_id) "
                "VALUES ('flag-1', 'hash-same', %s, %s), ('flag-2', 'hash-legacy', %s, %s)",
                (legacy_matched, TEAM_ID, legacy_matched, TEAM_ID),
            )
            cursor.execute(
                "INSERT INTO personhog_featureflaghashkeyoverride_tmp (feature_flag_key, hash_key, person_id, team_id) "
                "VALUES ('flag-1', 'hash-same', %s, %s), ('flag-2', 'hash-personhog', %s, %s), "
                "('flag-3', 'hash-tombstoned', %s, %s)",
                (ph_matched, TEAM_ID, ph_matched, TEAM_ID, ph_tombstoned, TEAM_ID),
            )

        reports = {report.category: report for report in compute_shadow_drift(connection, sample_size=10)}
    finally:
        connection.close()

    persons = reports["persons"]
    assert (persons.legacy_total, persons.personhog_total) == (3, 3)
    assert (persons.missing_in_personhog, persons.missing_in_legacy, persons.mismatched_rows) == (1, 1, 1)
    assert persons.field_mismatches == {"properties": 1, "is_identified": 0, "created_at": 0, "version": 1}
    assert persons.drift_pct == 75.0
    assert sorted(sample.rsplit(" ", 1)[1] for sample in persons.samples) == [
        "field_mismatch",
        "missing_in_legacy",
        "missing_in_personhog",
    ]

    distinct_ids = reports["distinct_ids"]
    assert (distinct_ids.legacy_total, distinct_ids.personhog_total) == (2, 2)
    assert (distinct_ids.missing_in_personhog, distinct_ids.missing_in_legacy, distinct_ids.mismatched_rows) == (
        0,
        0,
        1,
    )
    assert distinct_ids.samples == [
        f"team={TEAM_ID} distinct_id='shadow-drift-did-2' "
        f"legacy_person={matched} personhog_person={props_differ} person_mismatch"
    ]

    hash_keys = reports["hash_key_overrides"]
    assert (hash_keys.legacy_total, hash_keys.personhog_total) == (2, 2)
    assert (hash_keys.missing_in_personhog, hash_keys.missing_in_legacy, hash_keys.mismatched_rows) == (0, 0, 1)
    assert hash_keys.samples == [f"team={TEAM_ID} person={matched} flag=flag-2 hash_key_mismatch"]

import uuid

import pytest

import psycopg2
import psycopg2.extras

from posthog.dags.personhog_shadow_drift import compute_shadow_drift
from posthog.persons_db import persons_db_url

TEAM_ID = 990000123
CREATED_AT = "2026-01-01T00:00:00+00:00"


def _insert_person(cursor, table: str, person_uuid: uuid.UUID, properties: dict, is_deleted: bool = False) -> int:
    cursor.execute(
        f"INSERT INTO {table} (created_at, properties, is_identified, uuid, version, team_id, is_deleted) "
        "VALUES (%s, %s, false, %s, 1, %s, %s) RETURNING id",
        (CREATED_AT, psycopg2.extras.Json(properties), str(person_uuid), TEAM_ID, is_deleted),
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
        baseline = {report.category: report for report in compute_shadow_drift(connection, sample_size=0)}

        with connection.cursor() as cursor:
            legacy_matched = _insert_person(cursor, "posthog_person", matched, {"a": 1})
            _insert_person(cursor, "posthog_person", legacy_only, {})
            _insert_person(cursor, "posthog_person", props_differ, {"b": 1})

            ph_matched = _insert_person(cursor, "personhog_person_tmp", matched, {"a": 1})
            _insert_person(cursor, "personhog_person_tmp", personhog_only, {})
            ph_props = _insert_person(cursor, "personhog_person_tmp", props_differ, {"b": 2})
            _insert_person(cursor, "personhog_person_tmp", tombstoned, {}, is_deleted=True)

            cursor.execute(
                "INSERT INTO posthog_persondistinctid (distinct_id, version, person_id, team_id) VALUES "
                "('shadow-drift-did-1', 1, %s, %s), ('shadow-drift-did-2', 1, %s, %s)",
                (legacy_matched, TEAM_ID, legacy_matched, TEAM_ID),
            )
            cursor.execute(
                "INSERT INTO personhog_persondistinctid_tmp (distinct_id, version, person_id, team_id) VALUES "
                "('shadow-drift-did-1', 1, %s, %s), ('shadow-drift-did-2', 1, %s, %s)",
                (ph_matched, TEAM_ID, ph_props, TEAM_ID),
            )

            cursor.execute(
                "INSERT INTO posthog_featureflaghashkeyoverride (feature_flag_key, hash_key, person_id, team_id) "
                "VALUES ('flag-1', 'hash-same', %s, %s), ('flag-2', 'hash-legacy', %s, %s)",
                (legacy_matched, TEAM_ID, legacy_matched, TEAM_ID),
            )
            cursor.execute(
                "INSERT INTO personhog_featureflaghashkeyoverride_tmp (feature_flag_key, hash_key, person_id, team_id) "
                "VALUES ('flag-1', 'hash-same', %s, %s), ('flag-2', 'hash-personhog', %s, %s)",
                (ph_matched, TEAM_ID, ph_matched, TEAM_ID),
            )

        reports = {report.category: report for report in compute_shadow_drift(connection, sample_size=0)}

        persons = reports["persons"]
        persons_before = baseline["persons"]
        assert persons.legacy_total - persons_before.legacy_total == 3
        assert persons.personhog_total - persons_before.personhog_total == 3
        assert persons.missing_in_personhog - persons_before.missing_in_personhog == 1
        assert persons.missing_in_legacy - persons_before.missing_in_legacy == 1
        assert persons.mismatched_rows - persons_before.mismatched_rows == 1
        assert persons.field_mismatches["properties"] - persons_before.field_mismatches["properties"] == 1

        distinct_ids = reports["distinct_ids"]
        distinct_ids_before = baseline["distinct_ids"]
        assert distinct_ids.legacy_total - distinct_ids_before.legacy_total == 2
        assert distinct_ids.personhog_total - distinct_ids_before.personhog_total == 2
        assert distinct_ids.mismatched_rows - distinct_ids_before.mismatched_rows == 1

        hash_keys = reports["hash_key_overrides"]
        hash_keys_before = baseline["hash_key_overrides"]
        assert hash_keys.legacy_total - hash_keys_before.legacy_total == 2
        assert hash_keys.personhog_total - hash_keys_before.personhog_total == 2
        assert hash_keys.mismatched_rows - hash_keys_before.mismatched_rows == 1
    finally:
        with connection.cursor() as cursor:
            for table in (
                "posthog_featureflaghashkeyoverride",
                "personhog_featureflaghashkeyoverride_tmp",
                "posthog_persondistinctid",
                "personhog_persondistinctid_tmp",
                "posthog_person",
                "personhog_person_tmp",
            ):
                cursor.execute(f"DELETE FROM {table} WHERE team_id = %s", (TEAM_ID,))
        connection.close()

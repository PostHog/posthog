"""
Fixtures for standalone Rust /flags integration tests.

No Django test framework. Tests use:
- Django ORM for bootstrapping the test environment (org, team, user, API key)
- psycopg2 for person/group inserts (bypassing event ingestion)
- requests for Django API calls (cohorts, flags)
- requests for Rust /flags evaluation

Django ORM is used only for the session-scoped bootstrap because models like
Organization and Team have many required fields that change across migrations.
Raw SQL for these would break whenever a column is added — which is exactly
the schema-drift problem this test suite was built to catch.
"""

import os
import json
import uuid
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

import psycopg2
import requests

DJANGO_API_URL = os.environ.get("DJANGO_API_URL", "http://localhost:8000")
RUST_FLAGS_URL = os.environ.get("FEATURE_FLAGS_SERVICE_URL", "http://localhost:3001")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://posthog:posthog@localhost:5432/test_posthog")
# Persons, distinct IDs, and cohort people live in a separate database in production.
# Falls back to the main DB for local dev where everything is in one database.
PERSONS_DATABASE_URL = os.environ.get("PERSONS_DATABASE_URL", DATABASE_URL)


@dataclass
class TestEnv:
    team_id: int
    project_id: int
    api_token: str
    personal_api_key: str


def _bootstrap_test_env() -> TestEnv:
    """Create org, project, team, user, and API key via Django ORM.

    Uses the ORM so we don't need to track schema changes in raw SQL.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

    import django

    django.setup()

    from posthog.models import Organization, Project, Team, User
    from posthog.models.personal_api_key import PersonalAPIKey

    org = Organization.objects.create(name="Rust Integration Test")
    project = Project.objects.create(id=Team.objects.increment_id_sequence(), organization=org)
    team = Team.objects.create(
        id=project.id,
        project=project,
        organization=org,
        api_token=f"phc_test_{uuid.uuid4().hex}",
    )
    user = User.objects.create_and_join(org, "rust-integration@test.posthog.com", "testpassword12345")

    key_value = f"phx_test_{uuid.uuid4().hex}"
    secure_value = hashlib.sha256(key_value.encode()).hexdigest()
    PersonalAPIKey.objects.create(
        user=user,
        label="rust-integration-test",
        secure_value=f"sha256${secure_value}",
        scopes=["*"],
    )

    return TestEnv(
        team_id=team.id,
        project_id=project.id,
        api_token=team.api_token,
        personal_api_key=key_value,
    )


@pytest.fixture(scope="session")
def env(django_db_blocker) -> TestEnv:
    """Bootstrap test environment with Django ORM.

    Uses django_db_blocker.unblock() because pytest-django blocks DB access
    outside of @pytest.mark.django_db tests. We need session-scoped writes
    that persist for the external Rust process, so the standard
    transactional_db fixture (which rolls back) isn't appropriate.
    """
    with django_db_blocker.unblock():
        return _bootstrap_test_env()


@pytest.fixture(scope="session")
def api_session(env: TestEnv) -> requests.Session:
    """HTTP session authenticated with the personal API key."""
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {env.personal_api_key}"
    return session


# ---------------------------------------------------------------------------
# Persons database helpers
# ---------------------------------------------------------------------------


@dataclass
class TestDB:
    """Thin wrapper around psycopg2 for inserting test entities.

    Manages two connections matching production topology:
    - persons_conn: persons, distinct IDs, cohort people (persons database)
    - main_conn: groups, group type mappings (main database)

    Raw SQL is appropriate here because these tables have stable, simple schemas
    and we specifically want to avoid the event ingestion pipeline.
    """

    persons_conn: Any  # psycopg2 connection
    main_conn: Any  # psycopg2 connection
    team_id: int

    def create_person(self, distinct_ids: list[str], properties: dict[str, Any]) -> int:
        cur = self.persons_conn.cursor()
        cur.execute(
            """
            INSERT INTO posthog_person (team_id, uuid, properties, created_at,
                                        properties_last_updated_at, properties_last_operation,
                                        is_identified, version)
            VALUES (%s, %s, %s, now(), '{}', '{}', false, 0)
            RETURNING id
            """,
            (self.team_id, str(uuid.uuid4()), json.dumps(properties)),
        )
        person_id = cur.fetchone()[0]
        for did in distinct_ids:
            cur.execute(
                """
                INSERT INTO posthog_persondistinctid (team_id, person_id, distinct_id, version)
                VALUES (%s, %s, %s, 0)
                """,
                (self.team_id, person_id, did),
            )
        return person_id

    def create_group(
        self,
        group_type: str,
        group_type_index: int,
        group_key: str,
        group_properties: dict[str, Any],
    ) -> None:
        # The Rust flags service reads groups from the persons database, so we
        # insert into both databases: the main DB (for Django API visibility)
        # and the persons DB (for Rust service queries).
        for conn in [self.main_conn, self.persons_conn]:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO posthog_grouptypemapping (team_id, project_id, group_type, group_type_index)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (self.team_id, self.team_id, group_type, group_type_index),
            )
            cur.execute(
                """
                INSERT INTO posthog_group (team_id, group_key, group_type_index,
                                           group_properties, created_at,
                                           properties_last_updated_at, properties_last_operation, version)
                VALUES (%s, %s, %s, %s, now(), '{}', '{}', 0)
                """,
                (self.team_id, group_key, group_type_index, json.dumps(group_properties)),
            )

    def add_to_static_cohort(self, person_id: int, cohort_id: int, version: int = 0) -> None:
        cur = self.persons_conn.cursor()
        cur.execute(
            """
            INSERT INTO posthog_cohortpeople (person_id, cohort_id, version)
            VALUES (%s, %s, %s)
            """,
            (person_id, cohort_id, version),
        )

    def set_cohort_type(self, cohort_id: int, cohort_type: str | None) -> None:
        """Override the cohort_type for a cohort (e.g. to 'realtime' or 'behavioral')."""
        cur = self.main_conn.cursor()
        cur.execute(
            "UPDATE posthog_cohort SET cohort_type = %s WHERE id = %s",
            (cohort_type, cohort_id),
        )

    def cleanup(self) -> None:
        # posthog_cohortpeople has no team_id — delete via cohort_id from the main DB
        persons_cur = self.persons_conn.cursor()
        main_cur = self.main_conn.cursor()

        main_cur.execute("SELECT id FROM posthog_cohort WHERE team_id = %s", (self.team_id,))
        cohort_ids = [row[0] for row in main_cur.fetchall()]
        if cohort_ids:
            persons_cur.execute(
                "DELETE FROM posthog_cohortpeople WHERE cohort_id = ANY(%s)",
                (cohort_ids,),
            )

        for table in ["posthog_persondistinctid", "posthog_person"]:
            persons_cur.execute(f"DELETE FROM {table} WHERE team_id = %s", (self.team_id,))  # noqa: S608

        for table in ["posthog_group", "posthog_grouptypemapping"]:
            main_cur.execute(f"DELETE FROM {table} WHERE team_id = %s", (self.team_id,))  # noqa: S608
            persons_cur.execute(f"DELETE FROM {table} WHERE team_id = %s", (self.team_id,))  # noqa: S608


@pytest.fixture()
def db(env: TestEnv, api: "DjangoAPI") -> Iterator[TestDB]:
    """Per-test database helper for persons, groups, and cohort membership.

    Depends on ``api`` so that pytest tears ``db`` down first (cleaning up
    cohort people by cohort ID) before ``api`` deletes the cohorts themselves.
    """
    persons_conn = psycopg2.connect(PERSONS_DATABASE_URL)
    persons_conn.autocommit = True
    main_conn = psycopg2.connect(DATABASE_URL)
    main_conn.autocommit = True
    test_db = TestDB(persons_conn=persons_conn, main_conn=main_conn, team_id=env.team_id)
    yield test_db
    test_db.cleanup()
    persons_conn.close()
    main_conn.close()


# ---------------------------------------------------------------------------
# Django API helpers
# ---------------------------------------------------------------------------


@dataclass
class DjangoAPI:
    """HTTP client for creating cohorts and flags via the Django API."""

    session: requests.Session
    base_url: str
    team_id: int

    def create_cohort(
        self, name: str, filters: dict[str, Any] | None = None, is_static: bool = False
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"name": name}
        if filters is not None:
            data["filters"] = json.dumps(filters)
        if is_static:
            data["is_static"] = "true"
        resp = self.session.post(
            f"{self.base_url}/api/projects/{self.team_id}/cohorts/",
            data=data,
        )
        assert resp.status_code == 201, f"Failed to create cohort: {resp.text}"
        return resp.json()

    def create_flag(
        self,
        key: str,
        filters: dict[str, Any],
        active: bool = True,
    ) -> dict[str, Any]:
        resp = self.session.post(
            f"{self.base_url}/api/projects/{self.team_id}/feature_flags/",
            json={"key": key, "name": key, "filters": filters, "active": active},
        )
        assert resp.status_code == 201, f"Failed to create flag: {resp.text}"
        return resp.json()

    def cleanup(self) -> None:
        """Delete all flags and cohorts created during this test.

        Feature flags use soft delete (PATCH with deleted=true) because the
        viewset doesn't expose a DELETE action. Cohorts support DELETE.
        """
        for resource in ["feature_flags", "cohorts"]:
            resp = self.session.get(
                f"{self.base_url}/api/projects/{self.team_id}/{resource}/",
                params={"limit": 1000},
            )
            if not resp.ok:
                continue
            for item in resp.json().get("results", []):
                url = f"{self.base_url}/api/projects/{self.team_id}/{resource}/{item['id']}/"
                if resource == "feature_flags":
                    self.session.patch(url, json={"deleted": True})
                else:
                    self.session.delete(url)


@pytest.fixture()
def api(api_session: requests.Session, env: TestEnv) -> Iterator[DjangoAPI]:
    client = DjangoAPI(session=api_session, base_url=DJANGO_API_URL, team_id=env.team_id)
    yield client
    client.cleanup()


# ---------------------------------------------------------------------------
# Rust /flags helper
# ---------------------------------------------------------------------------


def evaluate_flags(
    api_token: str,
    distinct_id: str,
    groups: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Call the Rust /flags endpoint."""
    payload: dict[str, Any] = {"token": api_token, "distinct_id": distinct_id}
    if groups:
        payload["groups"] = groups
    resp = requests.post(f"{RUST_FLAGS_URL}/flags", params={"v": "2"}, json=payload, timeout=10)
    assert resp.ok, f"Rust /flags returned {resp.status_code}: {resp.text}"
    return resp.json()

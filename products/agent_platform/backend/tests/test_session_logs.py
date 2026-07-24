"""
Regression: AgentApplicationViewSet.session_logs — per-session log fetch.

Exercises the full Django → ClickHouse path so the class of bugs we hit
landing this endpoint (PAT scope missing, untagged CH query, wrong
default CH database) all get caught by CI:

  * inserts a real row into the `log_entries` CH table
  * hits `/agent_applications/<slug>/sessions/<session_id>/logs/`
  * asserts 200 + the row comes back
  * also asserts the action is declared as a scoped read action so
    PAT / OAuth callers with `agents:read` aren't rejected
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from rest_framework import status

from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.log_entries import INSERT_LOG_ENTRY_SQL

from ..models import AgentApplication
from ..presentation.views import AGENT_SESSION_LOG_SOURCE, AgentApplicationViewSet


def _insert_log(
    team_id: int,
    application_id: str,
    session_id: str,
    level: str = "INFO",
    message: str = "[meta] session_started",
    when: str | None = None,
) -> None:
    sync_execute(
        INSERT_LOG_ENTRY_SQL,
        {
            "team_id": team_id,
            "log_source": AGENT_SESSION_LOG_SOURCE,
            "log_source_id": application_id,
            "instance_id": session_id,
            "timestamp": when or datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
            "level": level,
            "message": message,
        },
    )


class TestSessionLogs(ClickhouseTestMixin, APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="hello",
            name="Hello agent",
            description="",
        )
        self.session_id = str(uuid4())

    def _url(self, session_id: str | None = None) -> str:
        sid = session_id or self.session_id
        return f"/api/projects/{self.team.id}/agent_applications/{self.application.slug}/sessions/{sid}/logs/"

    # ── happy path ──────────────────────────────────────────────────

    def test_returns_empty_when_no_logs(self) -> None:
        # Sanity: the endpoint reaches CH and returns a cleanly empty
        # result rather than 404/500 when the session has no logs yet.
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.json(), {"results": []})

    def test_returns_inserted_rows_for_session(self) -> None:
        # Inserts two rows for the target session + one decoy for a
        # different session and asserts only the target's land back.
        _insert_log(
            self.team.id,
            str(self.application.id),
            self.session_id,
            level="INFO",
            message="[meta] session_started",
            when="2026-05-29 12:00:00.000000",
        )
        _insert_log(
            self.team.id,
            str(self.application.id),
            self.session_id,
            level="INFO",
            message="[event] completed",
            when="2026-05-29 12:00:01.000000",
        )
        _insert_log(
            self.team.id,
            str(self.application.id),
            "00000000-0000-0000-0000-000000000099",  # different session
            level="INFO",
            message="should not appear",
        )

        res = self.client.get(self._url())
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.json()["results"]
        self.assertEqual(len(results), 2)
        # Newest first — `fetch_log_entries` does `ORDER BY timestamp DESC`.
        messages = [r["message"] for r in results]
        self.assertEqual(messages, ["[event] completed", "[meta] session_started"])

    def test_filter_by_level(self) -> None:
        _insert_log(self.team.id, str(self.application.id), self.session_id, level="INFO", message="info row")
        _insert_log(self.team.id, str(self.application.id), self.session_id, level="ERROR", message="error row")

        res = self.client.get(self._url(), {"level": "ERROR"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        messages = [r["message"] for r in res.json()["results"]]
        self.assertEqual(messages, ["error row"])

    def test_search_substring(self) -> None:
        _insert_log(self.team.id, str(self.application.id), self.session_id, message="[tool] assistant_text foo")
        _insert_log(self.team.id, str(self.application.id), self.session_id, message="[meta] session_started")

        res = self.client.get(self._url(), {"search": "foo"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        messages = [r["message"] for r in res.json()["results"]]
        self.assertEqual(messages, ["[tool] assistant_text foo"])

    # ── 404s + cross-team isolation ─────────────────────────────────

    def test_unknown_application_slug_404s(self) -> None:
        res = self.client.get(
            f"/api/projects/{self.team.id}/agent_applications/does-not-exist/sessions/{self.session_id}/logs/"
        )
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # ── PAT / OAuth scope hygiene ───────────────────────────────────

    def test_session_logs_is_a_declared_read_action(self) -> None:
        # Regression for the 403 we shipped — the PAT/OAuth scope check
        # rejects any action not listed in `scope_object_read_actions`
        # or `_write_actions` with "This action does not support
        # personal API key access". Lock the membership down.
        self.assertIn("session_logs", AgentApplicationViewSet.scope_object_read_actions)

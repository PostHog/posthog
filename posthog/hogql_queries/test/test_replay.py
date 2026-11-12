import json
import uuid
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command

from parameterized import parameterized

from posthog.clickhouse.client import sync_execute
from posthog.hogql_queries import replay
from posthog.hogql_queries.replay import CompiledQuery, LoggedQuery, RunResult, Verdict
from posthog.storage import object_storage

STARTED_AT = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
ROWS = RunResult(row_count=1, fingerprint=11)
OTHER_ROWS = RunResult(row_count=1, fingerprint=22)
FAILED = RunResult(error="boom")


class TestReplay(ClickhouseTestMixin, APIBaseTest):
    def _logged(self, query: dict | str, prod_sql: str = "", team_id: int | None = None) -> LoggedQuery:
        return LoggedQuery(
            query_id="q1",
            team_id=team_id or self.team.pk,
            kind="HogQLQuery",
            query_json=query if isinstance(query, str) else json.dumps(query),
            prod_sql=prod_sql,
            started_at=STARTED_AT,
        )

    def test_compiles_one_statement_scoped_to_the_team(self):
        compiled = replay.compile_logged_query(
            self._logged({"kind": "HogQLQuery", "query": "select count() from events"})
        )

        assert compiled.error is None
        assert compiled.sql is not None
        assert f"equals(events.team_id, {self.team.pk})" in compiled.sql
        assert "%(" not in compiled.sql

    def test_relative_dates_resolve_from_the_logged_start_time(self):
        query = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview"}],
            "dateRange": {"date_from": "-7d"},
        }

        compiled = replay.compile_logged_query(self._logged(query))

        assert compiled.sql is not None
        assert "2026-01-08" in compiled.sql
        assert "2026-01-15" in compiled.sql

    @parameterized.expand(
        [
            ("missing_team", '{"kind": "HogQLQuery", "query": "select 1"}', 999_999_999),
            ("bad_json", "{not json", None),
            ("unknown_field", '{"kind": "HogQLQuery", "query": "select nope from events"}', None),
        ]
    )
    def test_compile_failures_become_errors(self, _name, query_json, team_id):
        compiled = replay.compile_logged_query(self._logged(query_json, team_id=team_id))

        assert compiled.sql is None
        assert compiled.error

    @parameterized.expand(
        [
            ("leading_comment", "/* user_id:1 */ SELECT 1", "SELECT 1"),
            ("whitespace", "SELECT\n  1   FROM  t", "SELECT 1 FROM t"),
            ("timestamp", "toDateTime64('2026-01-02 03:04:05.678901', 6, 'UTC')", "toDateTime64('<ts>', 6, 'UTC')"),
            ("date_kept", "toDate('2026-01-02')", "toDate('2026-01-02')"),
            ("execution_cap", "SETTINGS max_execution_time=600, x=1", "SETTINGS max_execution_time=<n>, x=1"),
        ]
    )
    def test_normalize_sql(self, _name, raw, expected):
        assert replay.normalize_sql(raw) == expected

    @parameterized.expand(
        [
            ("identical_sql", "PROD", "PROD", {}, Verdict.IDENTICAL_SQL, 0),
            ("same_results", "PROD", "HEAD", {"PROD": [ROWS, ROWS], "HEAD": [ROWS]}, Verdict.SAME_RESULTS, 3),
            ("different", "PROD", "HEAD", {"PROD": [ROWS, ROWS], "HEAD": [OTHER_ROWS]}, Verdict.DIFFERENT_RESULTS, 3),
            ("unstable", "PROD", "HEAD", {"PROD": [ROWS, OTHER_ROWS]}, Verdict.UNSTABLE, 2),
            ("head_fails", "PROD", "HEAD", {"PROD": [ROWS, ROWS], "HEAD": [FAILED]}, Verdict.HEAD_ONLY_ERROR, 3),
            ("base_fails", "PROD", "HEAD", {"PROD": [FAILED]}, Verdict.NOT_RUN, 1),
            ("base_differs_from_prod", "OTHER", "HEAD", {}, Verdict.COULD_NOT_MODEL, 0),
            ("base_did_not_compile", None, "HEAD", {}, Verdict.COULD_NOT_MODEL, 0),
            ("head_did_not_compile", "PROD", None, {}, Verdict.HEAD_ONLY_ERROR, 0),
        ]
    )
    def test_verdicts(self, _name, base_sql, head_sql, results, verdict, expected_runs):
        calls: list[str] = []

        def execute(sql: str, team_id: int, tag: str) -> RunResult:
            calls.append(sql)
            return results[sql].pop(0)

        logged = self._logged({}, prod_sql="/* tag */ PROD")
        outcomes = replay.run_replay(
            [logged],
            {"q1": CompiledQuery(query_id="q1", sql=base_sql, error=None if base_sql else "x")},
            {"q1": CompiledQuery(query_id="q1", sql=head_sql, error=None if head_sql else "x")},
            execute,
        )

        assert outcomes[0].verdict is verdict
        assert len(calls) == expected_runs

    def test_execution_cap_leaves_the_rest_not_run(self):
        sample = [
            LoggedQuery(query_id=f"q{i}", team_id=1, kind="k", query_json="{}", prod_sql="PROD", started_at=STARTED_AT)
            for i in range(3)
        ]
        base = {q.query_id: CompiledQuery(query_id=q.query_id, sql="PROD") for q in sample}
        head = {q.query_id: CompiledQuery(query_id=q.query_id, sql="HEAD") for q in sample}

        outcomes = replay.run_replay(sample, base, head, lambda sql, team_id, tag: ROWS, max_executed=2)

        assert [o.verdict for o in outcomes] == [Verdict.SAME_RESULTS, Verdict.SAME_RESULTS, Verdict.NOT_RUN]

    def test_summary_flags_a_read_bytes_regression(self):
        outcome = replay.Outcome(
            logged=self._logged({}),
            verdict=Verdict.SAME_RESULTS,
            base_tag="replay-a-0-base",
            head_tag="replay-a-0-head",
        )

        def regressions(head_bytes: int) -> int:
            read_bytes = {"replay-a-0-base": 100, "replay-a-0-head": head_bytes}
            return replay.summarize([outcome], read_bytes, "b", "h")["regressions"]

        assert regressions(151) == 1
        assert regressions(150) == 0

    @parameterized.expand(
        [
            ("renamed_column", "SELECT 1 AS a", "SELECT 1 AS b"),
            ("changed_type", "SELECT 1 AS a", "SELECT 1.0 AS a"),
            ("changed_value", "SELECT 1 AS a", "SELECT 2 AS a"),
        ]
    )
    def test_fingerprint_tells_results_apart(self, _name, base_sql, head_sql):
        base = replay.execute_on_clickhouse(base_sql, self.team.pk, "replay-a-0-base")
        head = replay.execute_on_clickhouse(head_sql, self.team.pk, "replay-a-0-head")

        assert base.error is None
        assert not replay.results_match(base, head)

    @parameterized.expand(
        [
            ("same", [(1, "a")], [(1, "a")], True),
            ("reordered", [(1,), (2,)], [(2,), (1,)], True),
            ("duplicate_count", [(1,), (1,)], [(1,)], False),
            ("float_noise", [(0.1 + 0.2,)], [(0.3,)], True),
            ("float_change", [(0.30,)], [(0.31,)], False),
            ("nan", [(float("nan"),)], [(float("nan"),)], True),
            ("null_is_not_zero", [(None,)], [(0,)], False),
            ("nested", [([1, (2.0, None)],)], [([1, (2.0, None)],)], True),
            ("both_empty", [], [], True),
        ]
    )
    def test_rows_match(self, _name, base_rows, head_rows, expected):
        base = RunResult(row_count=len(base_rows), rows=tuple(base_rows))
        head = RunResult(row_count=len(head_rows), rows=tuple(head_rows))

        assert replay.results_match(base, head) is expected

    def test_row_differences_name_the_rows_on_each_side(self):
        base_only, head_only = replay.row_differences([(1, "a"), (2, "b")], [(1, "a"), (2, "c"), (3, "d")])

        assert base_only == [(2, "b")]
        assert head_only == [(2, "c"), (3, "d")]

    def test_results_over_the_row_cap_are_still_compared(self):
        with patch.object(replay, "ROW_CAP", 2):
            base = replay.execute_on_clickhouse("SELECT number FROM numbers(5)", self.team.pk, "replay-a-0-base")
            same = replay.execute_on_clickhouse("SELECT number FROM numbers(5)", self.team.pk, "replay-a-0-base2")
            head = replay.execute_on_clickhouse("SELECT number + 1 FROM numbers(5)", self.team.pk, "replay-a-0-head")

        assert base.rows is None
        assert replay.results_match(base, same)
        assert not replay.results_match(base, head)

    def test_compile_does_not_run_statements_sent_outside_hogql(self):
        query = {"kind": "HogQLQuery", "query": "select 1"}

        def calculate_with_a_side_query(runner):
            sync_execute("SELECT 1")

        with patch("posthog.hogql_queries.hogql_query_runner.HogQLQueryRunner.calculate", calculate_with_a_side_query):
            compiled = replay.compile_logged_query(self._logged(query))

        assert compiled.sql is None
        assert compiled.error == "Runner issued 1 statements"

    def test_report_folder_round_trips_through_object_storage(self):
        key = f"test_hogql_replay/{uuid.uuid4()}"
        with self.settings(OBJECT_STORAGE_ENABLED=True), tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            (tmp / "report" / "sql").mkdir(parents=True)
            (tmp / "report" / "index.html").write_text("<p>report</p>")
            (tmp / "report" / "sql" / "q1.head.sql").write_text("SELECT 1")

            replay.upload(tmp / "report", key)
            replay.download(f"{key}/sql/q1.head.sql", tmp / "copy.sql")
            copied = (tmp / "copy.sql").read_text()
            page = object_storage.object_storage_client().head_object(
                settings.OBJECT_STORAGE_BUCKET, f"{key}/index.html"
            )

        assert copied == "SELECT 1"
        assert page is not None
        assert page["ContentType"] == "text/html"

    def test_sample_query_matches_the_archive_schema(self):
        assert len(replay.load_logged_queries(sample_size=5)) <= 5
        assert replay.load_logged_queries(query_ids=["missing"]) == []

    def test_end_to_end_flags_a_head_that_changes_results(self):
        _create_event(team=self.team, event="a", distinct_id="1")
        _create_event(team=self.team, event="a", distinct_id="1")
        _create_event(team=self.team, event="b", distinct_id="1")
        query = {"kind": "HogQLQuery", "query": "select event, count() from events where event = 'a' group by event"}
        prod_sql = replay.compile_logged_query(self._logged(query)).sql
        assert prod_sql is not None
        logged = self._logged(query, prod_sql=prod_sql)

        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            replay.write_jsonl(tmp / "sample.jsonl", [logged])
            call_command("hogql_replay", "compile", sample_file=tmp / "sample.jsonl", out=tmp / "base.jsonl")
            head_sql = prod_sql.replace("'a'", "'b'")
            replay.write_jsonl(tmp / "head.jsonl", [CompiledQuery(query_id="q1", sql=head_sql)])
            call_command(
                "hogql_replay",
                "run",
                sample_file=tmp / "sample.jsonl",
                base=tmp / "base.jsonl",
                head=tmp / "head.jsonl",
                out_dir=tmp / "report",
                query_log_wait_seconds=0,
            )
            result = json.loads((tmp / "report" / "result.json").read_text())
            report = (tmp / "report" / "index.html").read_text()
            query = result["queries"][0]
            saved_base_sql = (tmp / "report" / query["base_sql_file"]).read_text()
            saved_head_sql = (tmp / "report" / query["head_sql_file"]).read_text()
            differences = json.loads((tmp / "report" / query["differences_file"]).read_text())

        assert result["counts"]["different_results"] == 1
        assert result["queries"][0]["base_rows"] == 1
        assert saved_base_sql == prod_sql
        assert saved_head_sql == head_sql
        assert differences["only_in_base"] == [["a", 2]]
        assert differences["only_in_head"] == [["b", 1]]
        assert "Rows only in head" in report
        assert "-" in report and "event" in report

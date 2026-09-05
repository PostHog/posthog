import re
import csv
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Optional

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.activity_logging.activity_log import ActivityLog

from products.actions.backend.models.action import Action
from products.actions.backend.selector_audit.audit import (
    BUCKET_DEPLOY_DAY_REWRITE,
    BUCKET_GAIN_ONLY,
    BUCKET_NO_DATA,
    BUCKET_NO_FAITHFUL_FIX,
    BUCKET_NOT_MEASURED,
    BUCKET_SAFE_REWRITE,
    BUCKET_UNCHANGED,
    COUNT_KEYS,
    apply_rewrites,
    build_report,
    carry_over_previous,
    count_autocapture_events,
    decide_bucket,
    detect_live_compiler,
    diff_reports,
    discover_rows,
    load_report,
    measure_team_rows,
    prefill_counts_from_previous,
    save_report,
)
from products.actions.backend.selector_audit.compilers import (
    classify_selector,
    compile_new,
    compile_old,
    rewrite_direct_descendants,
)
from products.product_analytics.backend.models.insight import Insight

DIRECT_SPAN_CHAIN = 'span.title:nth-child="1";div:attr_id="root"nth-child="1"'
DEEP_SPAN_CHAIN = 'span.title:nth-child="1";div.wrap:nth-child="2";div:attr_id="root"nth-child="1"'
DATA_ATTR_CHAIN = 'a.LemonButton:attr__data-attr="menu-item"href="/x"nth-child="1"'
ADJACENT_BUTTON_CHAIN = 'button.btn:nth-child="1";div.inner:nth-child="1";section.hero:nth-child="1"'
GAPPED_BUTTON_CHAIN = (
    'button.btn:nth-child="1";div.inner:nth-child="1";article.mid:nth-child="1";section.hero:nth-child="1"'
)
JUNK_DIV_CHAIN = 'button.btn:text="pay div now";body:nth-child="1"'
CLEAN_DIV_CHAIN = 'button.btn:text="pay now";div.wrap:nth-child="1";body:nth-child="1"'
SIBLING_SLASH_CHAIN = 'div.flex.w-1/2:nth-child="1";main:nth-child="1"'
ESCAPED_QUOTE_CHAIN = 'a.link:attr__data-name="say \\"hi\\""href="/x"nth-child="1"'


def _noop_log(_message: str) -> None:
    pass


def _steps(action: Action) -> list[dict[str, Any]]:
    assert action.steps_json is not None
    return action.steps_json


def make_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "team_id": 1,
        "action_id": 1,
        "action_name": "action",
        "step_index": 0,
        "selector": '[id="root"] > span',
        "rewrite": '[id="root"] span',
        "structure": "multi_part_direct",
        "flags": {"nth_child": False, "outside_old_allowlist": False, "unsupported_css": False},
        "counts": dict.fromkeys(COUNT_KEYS),
        "bucket": BUCKET_NOT_MEASURED,
        "suggestion": None,
        "references": None,
        "references_truncated": False,
        "applied_at": None,
    }
    row.update(overrides)
    return row


class TestCompilerSemantics(SimpleTestCase):
    @parameterized.expand(
        [
            ("direct_child_matches_both", '[id="root"] > span', DIRECT_SPAN_CHAIN, True, True),
            ("old_direct_child_reaches_deep", '[id="root"] > span', DEEP_SPAN_CHAIN, True, False),
            ("space_rewrite_matches_both_deep", '[id="root"] span', DEEP_SPAN_CHAIN, True, True),
            ("old_bare_tag_space_needs_adjacency", "section div button", GAPPED_BUTTON_CHAIN, False, True),
            ("adjacent_bare_tags_match_both", "section div button", ADJACENT_BUTTON_CHAIN, True, True),
            ("old_matches_tag_inside_text", "div > button", JUNK_DIV_CHAIN, True, False),
            ("real_parent_matches_both", "div > button", CLEAN_DIV_CHAIN, True, True),
            ("widened_tail_traverses_sibling_slash_class", "div.flex", SIBLING_SLASH_CHAIN, True, True),
            ("old_normalizes_bare_quotes_in_attr_value", "[data-name='say \"hi\"']", ESCAPED_QUOTE_CHAIN, True, False),
            ("simple_attr_matches_both", '[data-attr="menu-item"]', DATA_ATTR_CHAIN, True, True),
        ]
    )
    def test_vendored_compiler_behavior(
        self, _name: str, selector: str, chain: str, old_matches: bool, new_matches: bool
    ) -> None:
        assert bool(re.search(compile_old(selector), chain)) is old_matches
        assert bool(re.search(compile_new(selector), chain)) is new_matches


class TestRewriteDirectDescendants(SimpleTestCase):
    @parameterized.expand(
        [
            ("attr_then_direct", '[id="root"] > span', '[id="root"] span'),
            ("bare_tag_chain", "section > div > button", "section div button"),
            ("gt_inside_attr_value_kept", 'a[data-x="a > b"] > span', 'a[data-x="a > b"] span'),
            ("star_hop_erased_like_compiler", "section > div > * > button", "section div button"),
            ("trailing_star_leaves_no_rewrite", "#root > *", "#root > *"),
            ("leading_star_kept", "* > a", "* a"),
            ("no_combinator_unchanged", ".btn", ".btn"),
            ("spacing_preserved_without_gt", "div  span", "div  span"),
        ]
    )
    def test_rewrite(self, _name: str, selector: str, expected: str) -> None:
        assert rewrite_direct_descendants(selector) == expected


class TestClassifySelector(SimpleTestCase):
    @parameterized.expand(
        [
            (".btn", "single_simple", False, False, False),
            ('[data-attr="x"]', "single_simple", False, False, False),
            ("button.btn.primary", "multi_condition", False, False, False),
            ("div span", "multi_part", False, False, False),
            ("#root > span", "multi_part_direct", False, False, False),
            ("li:nth-child(2)", "multi_condition", True, False, False),
            ("div.w-1/2", "multi_condition", False, True, False),
            ("button:hover", "single_simple", False, False, True),
        ]
    )
    def test_classification(
        self, selector: str, structure: str, nth_child: bool, outside_allowlist: bool, unsupported: bool
    ) -> None:
        classification = classify_selector(selector)
        assert classification.structure == structure
        assert classification.has_nth_child is nth_child
        assert classification.outside_old_allowlist is outside_allowlist
        assert classification.unsupported_css is unsupported


class TestDecideBucket(SimpleTestCase):
    @parameterized.expand(
        [
            ("identical", 1000, 1000, 1000, 1000, BUCKET_UNCHANGED),
            ("within_tolerance", 1000, 985, 985, 985, BUCKET_UNCHANGED),
            ("gain", 1000, 1500, 1000, 1500, BUCKET_GAIN_ONLY),
            ("noop_today_faithful_after", 1000, 100, 995, 1000, BUCKET_SAFE_REWRITE),
            ("rewrite_gains_within_allowance", 1000, 100, 1000, 1080, BUCKET_SAFE_REWRITE),
            ("faithful_after_but_not_noop", 1000, 100, 400, 995, BUCKET_DEPLOY_DAY_REWRITE),
            ("nothing_reproduces_old", 1000, 100, 1000, 500, BUCKET_NO_FAITHFUL_FIX),
            ("rewrite_gains_too_much", 1000, 100, 1000, 2000, BUCKET_NO_FAITHFUL_FIX),
            ("zero_traffic", 0, 0, 0, 0, BUCKET_NO_DATA),
        ]
    )
    def test_buckets(
        self, _name: str, old_original: int, new_original: int, old_rewritten: int, new_rewritten: int, bucket: str
    ) -> None:
        row = make_row(
            counts={
                "old_original": old_original,
                "new_original": new_original,
                "old_rewritten": old_rewritten,
                "new_rewritten": new_rewritten,
            }
        )
        decide_bucket(row, tolerance=0.02)
        assert row["bucket"] == bucket

    def test_unmeasured_rows_keep_their_bucket(self) -> None:
        row = make_row()
        decide_bucket(row, tolerance=0.02)
        assert row["bucket"] == BUCKET_NOT_MEASURED

    def test_no_faithful_fix_suggests_closest_variant(self) -> None:
        row = make_row(counts={"old_original": 1000, "new_original": 100, "old_rewritten": 1000, "new_rewritten": 500})
        decide_bucket(row, tolerance=0.02)
        assert row["suggestion"] == {"selector": '[id="root"] span', "new_count": 500}


class TestDetectLiveCompiler(SimpleTestCase):
    def test_live_compiler_is_recognized(self) -> None:
        assert detect_live_compiler() in ("old", "new")


class TestMeasureBatching(SimpleTestCase):
    def _run(self, rows: list[dict[str, Any]], batch_size: int = 40) -> tuple[list[dict[str, Any]], int]:
        queries: list[dict[str, Any]] = []
        batches_done = 0

        def fake_execute(query: str, params: dict[str, Any], **kwargs: Any) -> list[list[int]]:
            queries.append(params)
            return [[7] * sum(1 for key in params if key.startswith("regex_"))]

        def on_batch_done() -> None:
            nonlocal batches_done
            batches_done += 1

        with patch("products.actions.backend.selector_audit.audit.sync_execute", side_effect=fake_execute):
            measure_team_rows(
                1, rows, days=7, batch_size=batch_size, sleep_seconds=0, log=_noop_log, on_batch_done=on_batch_done
            )
        return queries, batches_done

    @staticmethod
    def _regexes(params: dict[str, Any]) -> set[str]:
        return {value for key, value in params.items() if key.startswith("regex_")}

    def test_distinct_selectors_measured_once_with_counts_fanned_out(self) -> None:
        rows = [
            make_row(action_id=1),
            make_row(action_id=2),
            make_row(action_id=3, selector=".btn", rewrite=None),
        ]
        queries, batches_done = self._run(rows, batch_size=1)
        assert len(queries) == 2
        assert batches_done == 2
        assert self._regexes(queries[0]) == {compile_old(".btn"), compile_new(".btn")}
        assert self._regexes(queries[1]) == {
            compile_old('[id="root"] > span'),
            compile_new('[id="root"] > span'),
            compile_old('[id="root"] span'),
            compile_new('[id="root"] span'),
        }
        assert all(row["counts"] == dict.fromkeys(COUNT_KEYS, 7) for row in rows)

    def test_resume_prefill_skips_already_measured_selectors(self) -> None:
        measured = make_row(action_id=1, counts=dict.fromkeys(COUNT_KEYS, 5), bucket=BUCKET_SAFE_REWRITE)
        previous = build_report([measured], {}, {"days": 7}, "old")
        rows = [make_row(action_id=1), make_row(action_id=2, selector=".btn", rewrite=None)]

        assert prefill_counts_from_previous(rows, previous) == 1
        queries, _ = self._run(rows)

        assert len(queries) == 1
        assert self._regexes(queries[0]) == {compile_old(".btn"), compile_new(".btn")}
        assert rows[0]["counts"] == dict.fromkeys(COUNT_KEYS, 5)
        assert rows[1]["counts"] == dict.fromkeys(COUNT_KEYS, 7)


class TestReportRoundtrip(SimpleTestCase):
    def test_save_load_and_diff(self) -> None:
        open_row = make_row(action_id=1, bucket=BUCKET_SAFE_REWRITE)
        fixed_row = make_row(action_id=2, bucket=BUCKET_NO_FAITHFUL_FIX)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.json"
            report = build_report([open_row, fixed_row], {1: 100}, {"days": 7}, "old")
            csv_path = save_report(path, report)
            assert load_report(path) == report
            assert csv_path.read_text().count("\n") == 3

            rerun_rows = [
                make_row(action_id=1, bucket=BUCKET_SAFE_REWRITE),
                make_row(action_id=2, bucket=BUCKET_UNCHANGED),
                make_row(action_id=3, bucket=BUCKET_DEPLOY_DAY_REWRITE),
            ]
            diff = diff_reports(report, rerun_rows)
            assert [key.split(":")[1] for key in diff["fixed"]] == ["2"]
            assert [key.split(":")[1] for key in diff["still_open"]] == ["1"]
            assert [key.split(":")[1] for key in diff["new"]] == ["3"]

    def test_csv_cells_cannot_start_a_spreadsheet_formula(self) -> None:
        hostile = make_row(action_name='=HYPERLINK("https://example.com")', selector="-moz-only > span")
        with TemporaryDirectory() as tmp:
            csv_path = save_report(Path(tmp) / "audit.json", build_report([hostile], {}, {"days": 7}, "old"))
            with open(csv_path, newline="") as file:
                data_row = list(csv.reader(file))[1]
        assert data_row[2] == '\'=HYPERLINK("https://example.com")'
        assert data_row[4] == "'-moz-only > span"
        counts = {"old_original": 10, "new_original": 1, "old_rewritten": 10, "new_rewritten": 10}
        previous_row = make_row(bucket=BUCKET_SAFE_REWRITE, counts=counts, applied_at="2026-01-01T00:00:00Z")
        previous = build_report([previous_row], {}, {"days": 7}, "old")

        remeasured = make_row(counts=dict(counts), bucket=BUCKET_SAFE_REWRITE)
        carry_over_previous([remeasured], previous, keep_measurements=False)
        assert remeasured["applied_at"] == "2026-01-01T00:00:00Z"

        discovery_only = make_row()
        carry_over_previous([discovery_only], previous, keep_measurements=True)
        assert discovery_only["bucket"] == BUCKET_SAFE_REWRITE
        assert discovery_only["counts"] == counts
        assert discovery_only["applied_at"] == "2026-01-01T00:00:00Z"


class TestCommandGates(SimpleTestCase):
    @parameterized.expand(
        [
            ("deploy_day_needs_new_compiler", "old", ["--apply-deploy-day-rewrites"]),
            ("unknown_compiler_refuses_writes", "unknown", ["--apply-safe-rewrites"]),
        ]
    )
    def test_apply_gates(self, _name: str, live_compiler: str, flags: list[str]) -> None:
        with patch(
            "products.actions.backend.management.commands.audit_action_selectors.detect_live_compiler",
            return_value=live_compiler,
        ):
            with self.assertRaises(CommandError):
                call_command("audit_action_selectors", *flags, stdout=StringIO())

    def test_live_run_requires_an_apply_flag(self) -> None:
        with self.assertRaises(CommandError):
            call_command("audit_action_selectors", "--live-run", stdout=StringIO())


class TestMeasurementAndBuckets(ClickhouseTestMixin, BaseTest):
    def _create_chain_events(self, chain: str, count: int, timestamp: Optional[str] = None) -> None:
        for index in range(count):
            _create_event(
                team=self.team,
                event="$autocapture",
                distinct_id=f"user_{index}",
                elements_chain=chain,
                timestamp=timestamp,
            )

    def test_measure_and_bucket_end_to_end(self) -> None:
        safe = Action.objects.create(
            team=self.team, name="root span", steps_json=[{"event": "$autocapture", "selector": '[id="root"] > span'}]
        )
        unchanged = Action.objects.create(
            team=self.team,
            name="menu item",
            steps_json=[{"event": "$autocapture", "selector": '[data-attr="menu-item"]'}],
        )
        gain = Action.objects.create(
            team=self.team, name="buttons", steps_json=[{"event": "$autocapture", "selector": "section div button"}]
        )
        junk = Action.objects.create(
            team=self.team, name="junk div", steps_json=[{"event": "$autocapture", "selector": "div > button"}]
        )

        self._create_chain_events(DIRECT_SPAN_CHAIN, 5)
        self._create_chain_events(DEEP_SPAN_CHAIN, 10)
        self._create_chain_events(DATA_ATTR_CHAIN, 8)
        self._create_chain_events(ADJACENT_BUTTON_CHAIN, 4)
        self._create_chain_events(GAPPED_BUTTON_CHAIN, 6)
        self._create_chain_events(JUNK_DIV_CHAIN, 6)
        self._create_chain_events(CLEAN_DIV_CHAIN, 4)
        # Outside the measurement window: must not count toward any selector.
        self._create_chain_events(DATA_ATTR_CHAIN, 1, timestamp="2020-01-01T00:00:00Z")
        flush_persons_and_events()

        assert count_autocapture_events(self.team.pk, days=7) == 43

        rows = discover_rows([self.team.pk])
        assert len(rows) == 4
        measure_team_rows(self.team.pk, rows, days=7, batch_size=40, sleep_seconds=0, log=_noop_log)
        for row in rows:
            decide_bucket(row, tolerance=0.02)

        by_action = {row["action_id"]: row for row in rows}
        safe_row = by_action[safe.pk]
        assert safe_row["counts"] == {"old_original": 15, "new_original": 5, "old_rewritten": 15, "new_rewritten": 15}
        assert safe_row["bucket"] == BUCKET_SAFE_REWRITE
        assert safe_row["rewrite"] == '[id="root"] span'

        unchanged_row = by_action[unchanged.pk]
        assert unchanged_row["counts"] == {
            "old_original": 8,
            "new_original": 8,
            "old_rewritten": 8,
            "new_rewritten": 8,
        }
        assert unchanged_row["bucket"] == BUCKET_UNCHANGED

        gain_row = by_action[gain.pk]
        assert gain_row["counts"] == {"old_original": 4, "new_original": 10, "old_rewritten": 4, "new_rewritten": 10}
        assert gain_row["bucket"] == BUCKET_GAIN_ONLY
        assert gain_row["rewrite"] is None

        junk_row = by_action[junk.pk]
        assert junk_row["counts"] == {
            "old_original": 20,
            "new_original": 14,
            "old_rewritten": 20,
            "new_rewritten": 14,
        }
        assert junk_row["bucket"] == BUCKET_NO_FAITHFUL_FIX
        assert junk_row["suggestion"] == {"selector": "div > button", "new_count": 14}


class TestApplyRewrites(BaseTest):
    def _make_action(self) -> Action:
        return Action.objects.create(
            team=self.team,
            name="Audit target",
            steps_json=[
                {"event": "$autocapture", "selector": '[id="root"] > span'},
                {"event": "$pageview"},
            ],
        )

    def _safe_row(self, action: Action) -> dict[str, Any]:
        return make_row(team_id=self.team.pk, action_id=action.pk, bucket=BUCKET_SAFE_REWRITE)

    def test_dry_run_writes_nothing(self) -> None:
        action = self._make_action()
        logs_before = ActivityLog.objects.filter(scope="Action", item_id=str(action.pk)).count()

        summary = apply_rewrites(
            [self._safe_row(action)], frozenset({BUCKET_SAFE_REWRITE}), live_run=False, log=_noop_log
        )

        assert summary == {"applied": 0, "skipped": 0, "planned": 1}
        action.refresh_from_db()
        assert _steps(action)[0]["selector"] == '[id="root"] > span'
        assert ActivityLog.objects.filter(scope="Action", item_id=str(action.pk)).count() == logs_before

    def test_live_run_rewrites_and_logs_activity(self) -> None:
        action = self._make_action()
        bytecode_before = action.bytecode
        row = self._safe_row(action)

        summary = apply_rewrites([row], frozenset({BUCKET_SAFE_REWRITE}), live_run=True, log=_noop_log)

        assert summary == {"applied": 1, "skipped": 0, "planned": 0}
        action.refresh_from_db()
        assert _steps(action)[0]["selector"] == '[id="root"] span'
        assert _steps(action)[1] == {"event": "$pageview"}
        # The narrowed update_fields write must still persist the bytecode that
        # save() recompiles, or destinations keep matching the old selector.
        assert action.bytecode is not None
        assert action.bytecode != bytecode_before
        assert row["applied_at"] is not None
        assert ActivityLog.objects.filter(scope="Action", item_id=str(action.pk), activity="updated").exists()

        rerun = apply_rewrites([row], frozenset({BUCKET_SAFE_REWRITE}), live_run=True, log=_noop_log)
        assert rerun == {"applied": 0, "skipped": 0, "planned": 0}

    def test_drifted_selector_is_skipped(self) -> None:
        action = self._make_action()
        row = self._safe_row(action)
        _steps(action)[0]["selector"] = ".changed-by-user"
        action.save()

        summary = apply_rewrites([row], frozenset({BUCKET_SAFE_REWRITE}), live_run=True, log=_noop_log)

        assert summary == {"applied": 0, "skipped": 1, "planned": 0}
        action.refresh_from_db()
        assert _steps(action)[0]["selector"] == ".changed-by-user"

    def test_other_buckets_are_never_touched(self) -> None:
        action = self._make_action()
        row = self._safe_row(action)
        row["bucket"] = BUCKET_NO_FAITHFUL_FIX

        summary = apply_rewrites([row], frozenset({BUCKET_SAFE_REWRITE}), live_run=True, log=_noop_log)

        assert summary == {"applied": 0, "skipped": 0, "planned": 0}
        action.refresh_from_db()
        assert _steps(action)[0]["selector"] == '[id="root"] > span'


class TestCommandSmoke(BaseTest):
    def test_discovery_only_run_writes_report_with_references(self) -> None:
        action = Action.objects.create(
            team=self.team,
            name="smoke",
            steps_json=[{"event": "$autocapture", "selector": ".btn"}],
            post_to_slack=True,
        )
        # Resolved dynamically: tach forbids products.actions (test files included)
        # from importing products.dashboards and products.surveys.
        dashboard_model = apps.get_model("dashboards", "Dashboard")
        tile_model = apps.get_model("dashboards", "DashboardTile")
        survey_model = apps.get_model("surveys", "Survey")
        insight = Insight.objects.create(team=self.team, filters={"actions": [{"id": action.pk, "type": "actions"}]})
        dashboard = dashboard_model.objects.create(team=self.team, name="smoke dashboard")
        tile_model.objects.create(dashboard=dashboard, insight=insight)
        survey = survey_model.objects.create(team=self.team, name="smoke survey", type="popover")
        survey.actions.add(action)

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.json"
            call_command(
                "audit_action_selectors", "--team-ids", str(self.team.pk), "--output", str(path), stdout=StringIO()
            )
            report = json.loads(path.read_text())
            rows = report["teams"][str(self.team.pk)]["rows"]
            assert [(row["action_id"], row["bucket"]) for row in rows] == [(action.pk, BUCKET_NOT_MEASURED)]
            references = {(ref["type"], ref["id"]) for ref in rows[0]["references"]}
            assert references == {
                ("insight", str(insight.short_id)),
                ("dashboard", str(dashboard.pk)),
                ("survey", str(survey.id)),
                ("webhook", str(action.pk)),
            }

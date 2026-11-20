import argparse
import subprocess
from pathlib import Path

import pytest

from hoglint_shadow import ChangedLines, HookFilter, OldToolEdits, ShadowReport, StagedChange, git_diff, report_findings
from parameterized import parameterized

# Real hoglint output and the real git diff of the same state. In the `.out` files every line is
# verbatim; the advisory list keeps its first row and the probes' rows, and each list of inherited
# unknowns keeps its first two rows.
# From hoglint 0.2.3 on the policy where public-surface, model-crossings and get-model only report:
# - advisory: `check --index --all` with shadow_probe.py added, a public-surface crossing. hoglint
#   exits 0, and the row is in the advisory list.
# - both: the same, with an import of Django added to visual_review's contracts at line 863, a
#   contracts-no-django finding that blocks.
# - compare: `compare --base HEAD --all` of the same staged change.
# - names: new files with a crossing each, one with a non-ASCII name and one with a space in it.
# - ledger: the contracts edit, and the ledger rewritten with `--record-growth` and staged.
# From hoglint 0.2.2, from a scratch worktree, on rules that still block:
# - rename: a facade function renamed, which breaks importers in files the commit does not stage.
# - config-error: stderr of `check --all` on a config with an unknown section.
# - placement: two new files where `temporal-placement` forbids them, one of them empty.
# - owned: one such new file in a directory with owners, so hoglint prints `at (no line)  [team]`.
FIXTURES = Path(__file__).parent / "fixtures" / "hoglint-shadow"

PROBE = "products/visual_review/backend/logic/shadow_probe.py"
CONTRACTS = "products/visual_review/backend/facade/contracts.py"
CAFE = "products/visual_review/backend/logic/café_probe.py"
SPACE = "products/visual_review/backend/logic/space probe.py"
LEDGER = "hoglint.ledger"
EXCEPTIONS = "hoglint.exceptions.toml"
REST = "findings are not on lines this commit changes; CI and the ledger catch-up judge them."
CONTINUES = "hoglint did not finish this check, so the commit continues. CI runs the full check."
VENV_HOGLINT = ".flox/cache/venv/bin/hoglint"
PROBE_ADVISORY = (
    "hoglint (advisory, does not block) public-surface at products/visual_review/backend/logic/shadow_probe.py:1: "
    "products.visual_review.backend.logic.shadow_probe names products.event_definitions.backend.models.event_definition.EventDefinition, "
    "which is not exported to it. If the facade of products.event_definitions exports this object, import it from the facade. "
    "If not, continue: CI records the coupling for the owners of products.event_definitions."
)

PRESET = "tools/hoglint/presets/posthog.toml"
LEDGER_DIFF_HEADER = "diff --git a/hoglint.ledger b/hoglint.ledger\n--- a/hoglint.ledger\n+++ b/hoglint.ledger\n"
# The exceptions file as the repo holds it, with no entry yet. The ci-scripts job does not check out
# the repo root's copy.
EXCEPTIONS_TEXT = """\
# Reviewed hoglint exceptions. A person writes each one, and the owners of this file review it.
# Each [[exception]] needs rule, match, reason, owners, scope ("prod" or "test") and review_by.
# An exception that matches no finding fails the check. `hoglint help hook` says when to add one.
schema = 1
"""
EXCEPTION_FIELDS = (
    'rule = "public-surface"\nmatch = { "src.module" = "products.visual_review.backend.logic.plain_probe" }\n'
    'reason = "The probe reads the schema model."\nowners = ["team-devex"]\nscope = "prod"\nreview_by = 2026-12-31\n'
)
EXCEPTION_SPACED = EXCEPTIONS_TEXT + "\n[[ exception ]]\n" + EXCEPTION_FIELDS
EXCEPTION_INLINE = EXCEPTIONS_TEXT + "exception = [ { " + EXCEPTION_FIELDS.strip().replace("\n", ", ") + " } ]\n"

# hoglint writes this line to stderr while it fills its pack memo (`core/memo.py`, MEMO_FILL).
MEMO_FILL = "hoglint: the pack memo is empty, so this check fills it. This check is slower than the next ones."


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def diff_of(name: str, path: str) -> str:
    """The sections of a captured diff whose header names the file."""
    sections = fixture(name).split("diff --git ")[1:]
    return "".join(f"diff --git {section}" for section in sections if path in section.splitlines()[0])


def hook(
    output: str,
    diff: str,
    staged: list[str],
    status: int = 1,
    stderr: str = "",
    added: list[str] | None = None,
    exceptions: tuple[str, str] = ("", ""),
    hoglint: str = "hoglint",
) -> tuple[int, str]:
    change = StagedChange(ChangedLines.of(diff, added), staged, *exceptions)
    return HookFilter(output, stderr, status, change, hoglint).verdict()


def report(output: str, diff: str, stderr: str = "", status: int = 1) -> ShadowReport:
    return ShadowReport(output, stderr, status, "Tuesday, Nov 24", ChangedLines.of(diff))


def with_lines(output: str, before: str, added: list[str]) -> str:
    """The output with lines added before the first line that starts with `before`."""
    lines = output.splitlines()
    at = next(index for index, line in enumerate(lines) if line.startswith(before))
    return "\n".join([*lines[:at], *added, *lines[at:]])


class TestHookFilter:
    def test_breaks_on_unchanged_lines_pass_without_calling_them_master_debt(self) -> None:
        code, text = hook(fixture("rename.out"), fixture("rename.diff"), ["products/security/backend/facade/api.py"], 2)
        assert code == 0
        assert text.splitlines()[-1] == f"25 {REST}"
        assert "master" not in text

    def test_a_finding_on_a_changed_line_blocks_with_hints_the_developer_can_run(self) -> None:
        code, text = hook(fixture("both.out"), fixture("both.diff"), [CONTRACTS, PROBE], hoglint=VENV_HOGLINT)
        assert code == 1
        assert text.splitlines() == [
            PROBE_ADVISORY,
            "contracts-no-django: products.visual_review.backend.facade.contracts reaches django.db.models: products.visual_review.backend.facade.contracts -> django.db.models",
            "  at products/visual_review/backend/facade/contracts.py:863  [team-devex]",
            "  why: A contracts module must import without Django. Other products and tools import contracts where Django is not set up.",
            "  fix (needs care): Break the chain at its first step. Move that import into the function that uses it, or under TYPE_CHECKING if only a type needs it.",
            "  fix (needs care): Move the code that needs Django out of the contracts module.",
            f"  see: {VENV_HOGLINT} explain contracts-no-django",
            "Fix each finding, or stop and tell the person. Do not edit hoglint.ledger, hoglint.exceptions.toml, hoglint.toml or a preset to make this check pass.",
            f"hoglint blocks findings on the lines this commit changes. Fix them, or run `{VENV_HOGLINT} explain contracts-no-django`.",
        ]

    @parameterized.expand(
        [
            ("hoglint_passes", "advisory.out", 0, [PROBE_ADVISORY, "hoglint: no new problems."]),
            (
                "a_finding_off_the_changed_lines",
                "both.out",
                1,
                [PROBE_ADVISORY, f"1 {REST.replace('findings are', 'finding is')}"],
            ),
        ]
    )
    def test_an_advisory_row_on_a_changed_line_passes_with_one_line_that_says_what_to_do(
        self, _name: str, output: str, status: int, expected: list[str]
    ) -> None:
        code, text = hook(fixture(output), diff_of("both.diff", "shadow_probe"), [PROBE], status, added=[PROBE])
        assert code == 0
        assert text.splitlines() == expected

    def test_debt_in_a_touched_file_off_the_changed_lines_passes(self) -> None:
        # No staged change can keep line 863 unchanged, because HEAD does not have it. This diff
        # edits line 5 of the same file, as a commit does on master after CI let the finding in.
        diff = f"diff --git a/{CONTRACTS} b/{CONTRACTS}\n--- a/{CONTRACTS}\n+++ b/{CONTRACTS}\n@@ -5 +5 @@\n-a = 1\n+a = 2\n"
        code, text = hook(fixture("both.out"), diff, [CONTRACTS])
        assert (code, text) == (0, f"1 {REST.replace('findings are', 'finding is')}")

    @parameterized.expand([("non_ascii_name", CAFE, "caf"), ("name_with_a_space", SPACE, "space probe")])
    def test_a_row_in_an_unusual_path_is_on_its_changed_line(self, _name: str, path: str, header: str) -> None:
        code, text = hook(fixture("names.out"), diff_of("names.diff", header), [path], 0)
        assert code == 0
        assert f"hoglint (advisory, does not block) public-surface at {path}:1: " in text

    @parameterized.expand([("with_other_files", [CONTRACTS, LEDGER], 1), ("alone", [LEDGER], 0)])
    def test_new_ledger_lines_block_only_with_other_files(self, _name: str, staged: list[str], expected: int) -> None:
        code, text = hook(fixture("ledger.out"), fixture("ledger.diff"), staged)
        assert code == expected
        assert "This change adds 1 line to hoglint.ledger, with no policy change." in text.splitlines()

    @parameterized.expand(
        [
            ("with_other_files", [PRESET, LEDGER, CONTRACTS], 1),
            ("alone", [LEDGER], 0),
        ]
    )
    def test_ledger_growth_blocks_even_when_a_policy_change_hides_it_from_hoglint(
        self, _name: str, staged: list[str], expected: int
    ) -> None:
        # With a policy change, hoglint judges no ledger growth and exits 0, so the glue reads the
        # staged ledger diff itself.
        code, _text = hook("hoglint: no new problems.\n", fixture("ledger.diff"), staged, status=0)
        assert code == expected

    def test_a_lowered_ledger_count_is_a_fix_and_passes(self) -> None:
        diff = (
            LEDGER_DIFF_HEADER
            + "@@ -9 +9 @@\n-public-surface\tsome.target\tsome.source\timport\t3\n+public-surface\tsome.target\tsome.source\timport\t2\n"
        )
        assert hook("hoglint: no new problems.\n", diff, [PRESET, LEDGER, CONTRACTS], status=0)[0] == 0

    def test_a_rename_with_its_re_recorded_ledger_passes(self) -> None:
        # Without a policy file staged, hoglint judges ledger growth, and it knows a move: this
        # rename plus `hoglint check --write-ledger` exits 0. The moved line's key names the new
        # module, so a key-by-key reading of the diff would call it new debt.
        old = "public-surface\tposthog.temporal.ai_observability.ACTIVITIES\tposthog.temporal.tests.ai.test_module_integrity"
        diff = (
            "diff --git a/posthog/temporal/tests/ai/test_module_integrity.py b/posthog/temporal/tests/ai/test_module_integrity_moved.py\n"
            "similarity index 100%\nrename from posthog/temporal/tests/ai/test_module_integrity.py\n"
            "rename to posthog/temporal/tests/ai/test_module_integrity_moved.py\n"
            f"{LEDGER_DIFF_HEADER}@@ -3468 +3468 @@\n-{old}\timport\t1\n+{old}_moved\timport\t1\n"
        )
        staged = ["posthog/temporal/tests/ai/test_module_integrity_moved.py", LEDGER]
        assert hook("hoglint: no new problems.\n", diff, staged, status=0)[0] == 0

    @parameterized.expand(
        [
            ("spaced_header_with_other_files", EXCEPTIONS_TEXT, EXCEPTION_SPACED, [EXCEPTIONS, CONTRACTS], 1),
            ("inline_table_with_other_files", EXCEPTIONS_TEXT, EXCEPTION_INLINE, [EXCEPTIONS, CONTRACTS], 1),
            (
                "comment_only_with_other_files",
                EXCEPTIONS_TEXT,
                EXCEPTIONS_TEXT + "# A note.\n",
                [EXCEPTIONS, CONTRACTS],
                0,
            ),
            ("removal_with_other_files", EXCEPTION_SPACED, EXCEPTIONS_TEXT, [EXCEPTIONS, CONTRACTS], 0),
            ("spaced_header_alone", EXCEPTIONS_TEXT, EXCEPTION_SPACED, [EXCEPTIONS], 0),
        ]
    )
    def test_a_new_exception_blocks_only_with_other_files(
        self, _name: str, before: str, after: str, staged: list[str], expected: int
    ) -> None:
        code, _text = hook("hoglint: no new problems.\n", "", staged, 0, exceptions=(before, after))
        assert code == expected

    def test_a_finding_at_no_line_in_an_owned_directory_blocks_when_its_file_is_new(self) -> None:
        added = ["posthog/temporal/alerts/placement_probe.py"]
        code, text = hook(fixture("owned.out"), fixture("owned.diff"), added, added=added)
        assert code == 1
        assert "  at (no line)  [team-product-analytics]" in text.splitlines()

    @parameterized.expand(
        [
            (
                "new_files",
                ["posthog/temporal/tests/ai/test_empty_probe.py", "posthog/temporal/tests/ai/test_placement_probe.py"],
                1,
            ),
            ("files_already_there", [], 0),
        ]
    )
    def test_a_finding_without_a_place_line_blocks_when_its_module_s_file_is_new(
        self, _name: str, added: list[str], expected: int
    ) -> None:
        diff = fixture("placement.diff") if added else ""
        code, text = hook(fixture("placement.out"), diff, added, added=added)
        assert code == expected
        assert (
            "temporal-placement: posthog.temporal.tests.ai.test_empty_probe is in a place that the rule does not allow"
            in text.splitlines()
        )
        assert (
            "temporal-placement: posthog.temporal.tests.ai.test_placement_probe is in a place that the rule does not allow"
            in text.splitlines()
        )
        if not expected:
            assert f"2 {REST}" in text.splitlines()

    def test_output_that_is_not_a_report_lets_the_commit_continue(self) -> None:
        code, text = hook("", "", [CONTRACTS], 2, fixture("config-error.err"))
        assert code == 0
        assert text.splitlines() == ["config error:", "  bogus: unknown section  [hoglint.toml]", CONTINUES]

    @parameterized.expand(
        [
            ("inside_a_finding", f"    at {CONTRACTS}:863", f"  at {CONTRACTS}:863  [team-devex]"),
            ("inside_an_advisory_row", f"    at {PROBE}:1", PROBE_ADVISORY),
        ]
    )
    def test_a_stray_line_inside_a_section_cuts_no_row(self, _name: str, before: str, expected: str) -> None:
        output = with_lines(fixture("both.out"), before, [MEMO_FILL])
        code, text = hook(output, fixture("both.diff"), [CONTRACTS, PROBE], added=[PROBE])
        assert code == 1
        assert expected in text.splitlines()

    def test_extractor_unknowns_and_rows_without_a_place_are_printed_and_counted(self) -> None:
        # No real run produced these two rows. They follow hoglint 0.2.2's format strings in
        # report.py: `unknown_line` with the extractor cause, and `place` for a finding with no path.
        no_place = [
            "  contracts-no-django: products.visual_review.backend.facade.contracts reaches django.db: products.visual_review.backend.facade.contracts -> django.db",
            "    at (no line)  [team-devex]",
        ]
        extractor = f"  contracts-no-django [extractor, not-modelled] {PROBE}:1: import 'products.event_definitions.backend.models' did not resolve"
        output = with_lines(fixture("both.out"), "advisory rows (6041)", no_place)
        output = with_lines(output, "unknowns attributed against", [extractor])
        code, text = hook(output, fixture("both.diff"), [CONTRACTS, PROBE], added=[PROBE])
        assert code == 1
        assert "  at (no line)  [team-devex]" in text.splitlines()
        assert extractor[2:] in text.splitlines()
        assert f"2 {REST}" in text.splitlines()


class TestShadowReport:
    def test_a_finding_on_a_changed_line_warns_and_an_advisory_row_there_is_a_notice(self) -> None:
        shadow = report(fixture("compare.out"), fixture("compare.diff"))
        assert shadow.annotations() == [
            f"::warning file={CONTRACTS},line=863,title=hoglint contracts-no-django (shadow)::products.visual_review.backend.facade.contracts reaches django.db.models: products.visual_review.backend.facade.contracts -> django.db.models",
            f"::notice file={PROBE},line=1,title=hoglint public-surface (advisory)::products.visual_review.backend.logic.shadow_probe names products.event_definitions.backend.models.event_definition.EventDefinition, which is not exported to it. Does not block. If the facade of products.event_definitions exports this object, import it from the facade. If not, continue: CI records the coupling for the owners of products.event_definitions.",
        ]

    def test_the_summary_says_only_the_rows_that_will_block_block(self) -> None:
        summary = report(fixture("compare.out"), fixture("compare.diff")).summary()
        blocks, rest = summary.split("**From this PR: reports only**")
        reports, others = rest.split("**Not on lines this PR changes")
        assert "From Tuesday, Nov 24 on, hoglint blocks the rows in this section." in blocks
        assert "contracts-no-django products.visual_review.backend.facade.contracts django.db.models" in blocks
        assert "public-surface" not in blocks
        assert "hoglint blocks" not in reports
        assert "public-surface products.event_definitions.backend.models.event_definition.EventDefinition" in reports
        assert f"  at {PROBE}:1  [team-devex]" in reports.splitlines()
        assert "  If the facade of products.event_definitions exports this object" in reports
        assert "contracts-no-django" not in reports
        assert "Advisory rows, which never block: 6041." in others

    def test_a_backtick_fence_in_a_row_cannot_close_the_summary_s_text_block(self) -> None:
        injected = "``` [all checks passed](https://example.com)"
        output = fixture("both.out").replace("-> django.db.models", injected, 1)
        summary = report(output, fixture("both.diff")).summary()
        lines = summary.split("\n")
        row = next(index for index, line in enumerate(lines) if injected in line)
        opening = next(line for line in reversed(lines[:row]) if line.startswith("```"))
        assert opening == "````text"
        assert "````" in lines[row + 1 :]

    def test_the_log_echo_runs_no_workflow_command_from_hoglint_s_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        output = tmp_path / "hoglint.txt"
        output.write_text("    at products/x/probe\r::error file=a.py,line=1::forged.py:1\n")
        args = argparse.Namespace(output=output, stderr=None, status=1, until="Tuesday, Nov 24")
        report_findings(args, ChangedLines())
        lines = capsys.readouterr().out.split("\n")
        stop = next(line for line in lines if line.startswith("::stop-commands::"))
        resume = f"::{stop.removeprefix('::stop-commands::')}::"
        forged = next(index for index, line in enumerate(lines) if "forged" in line)
        assert lines.index(stop) < forged < lines.index(resume)

    def test_the_summary_says_when_hoglint_did_not_run(self) -> None:
        shadow = report("", "", fixture("config-error.err"), 2)
        assert shadow.annotations() == []
        assert "hoglint did not run (exit 2): config error: bogus: unknown section  [hoglint.toml]" in shadow.summary()

    def test_the_summary_stays_small_when_a_pull_request_rewrites_the_ledger(self) -> None:
        ledger_row = next(
            line for line in fixture("ledger.diff").split("\n") if line.startswith("+contracts-no-django")
        )
        rows = [f"  {ledger_row[1:]}{index}" for index in range(9000)]
        output = with_lines(fixture("compare.out"), "ledger lines removed (0)", ["ledger lines added (9000)", *rows])
        summary = report(output, fixture("compare.diff")).summary()
        assert len(summary.encode()) < 64 * 1024
        assert "and 8950 more (full list in the log)" in summary


class TestChangedLines:
    def test_reads_a_quoted_non_ascii_path_and_a_path_with_a_space(self) -> None:
        assert {CAFE, SPACE} <= ChangedLines.of(fixture("names.diff")).new_files

    def test_a_line_separator_inside_a_line_keeps_the_hunk_counts(self) -> None:
        diff = (
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1 @@\n-x = ' \u2028-z'\n-y = 1\n+x = 2\n"
            "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@ -5 +5 @@\n-old = 1\n+new = 1\n"
        )
        assert ChangedLines.of(diff).lines == {"a.py": {1}, "b.py": {5}}

    def test_a_user_s_inter_hunk_context_keeps_hunks_apart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        def run(*args: str) -> None:
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], check=True)

        run("init", "-q")
        run("config", "diff.interHunkContext", "3")
        Path("m.py").write_text("a\nb\nc\nd\n")
        Path("z.py").write_text("x\n")
        run("add", ".")
        run("commit", "-qm", "base")
        Path("m.py").write_text("A\nb\nc\nD\n")
        Path("z.py").write_text("y\n")
        run("add", ".")
        assert ChangedLines.of(git_diff("--cached")).lines == {"m.py": {1, 4}, "z.py": {1}}


class TestOldToolEdits:
    def test_notes_only_edits_to_files_that_go_away(self) -> None:
        pyproject_diff = '@@ -640,6 +640,7 @@ ignore_imports = [\n+    "products.example.backend.facade.api -> products.example.backend.models",\n'
        edits = OldToolEdits(
            ["products/visual_review/backend/models.py", "tach.toml", "pyproject.toml"],
            pyproject_diff,
            "Tuesday, Nov 24",
        )
        assert edits.paths() == ["tach.toml", "pyproject.toml"]

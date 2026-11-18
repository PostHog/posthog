from pathlib import Path

from hoglint_shadow import ChangedLines, HookFilter, OldToolEdits, ShadowReport
from parameterized import parameterized

# Real hoglint 0.2.2 output and the real git diff of the same state, from a scratch worktree whose
# HEAD carries shadow_probe.py's two findings, as master does when CI lets them through. In the
# `.out` files every line is verbatim; the advisory list keeps its first row and the inherited
# unknowns their first two.
# - touched: `check --index --all` with shadow_probe.py edited on line 5 and shadow_schema.py added.
# - rename: a facade function renamed, which breaks importers in files the commit does not stage.
# - names: new files with a finding each, one with a non-ASCII name and one with a space in it.
# - ledger: plain_probe.py added, and the ledger rewritten with `--record-growth` and staged.
# - compare: `compare --base HEAD^1 --all` of the commit that added shadow_probe.py.
# - config-error: stderr of `check --all` on a config with an unknown section.
FIXTURES = Path(__file__).parent / "fixtures" / "hoglint-shadow"

PROBE = "products/visual_review/backend/logic/shadow_probe.py"
SCHEMA = "products/visual_review/backend/logic/shadow_schema.py"
CAFE = "products/visual_review/backend/logic/café_probe.py"
SPACE = "products/visual_review/backend/logic/space probe.py"
PLAIN = "products/visual_review/backend/logic/plain_probe.py"
LEDGER = "hoglint.ledger"
EXCEPTIONS = "hoglint.exceptions.toml"
REST = "findings are not on lines this commit changes; CI and the ledger catch-up judge them."
CONTINUES = "hoglint did not finish this check, so the commit continues. CI runs the full check."

# hoglint writes this line to stderr while it fills its pack memo (`core/memo.py`, MEMO_FILL).
MEMO_FILL = "hoglint: the pack memo is empty, so this check fills it. This check is slower than the next ones."


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def diff_of(name: str, path: str) -> str:
    """The sections of a captured diff whose header names the file."""
    sections = fixture(name).split("diff --git ")[1:]
    return "".join(f"diff --git {section}" for section in sections if path in section.splitlines()[0])


def hook(output: str, diff: str, staged: list[str], status: int = 1, stderr: str = "") -> tuple[int, str]:
    return HookFilter(output, stderr, status, diff, staged).verdict()


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

    def test_a_finding_on_a_changed_line_blocks_with_its_rule_guidance(self) -> None:
        code, text = hook(fixture("touched.out"), fixture("touched.diff"), [PROBE, SCHEMA])
        assert code == 1
        assert text.splitlines() == [
            "public-surface: products.visual_review.backend.logic.shadow_schema names products.event_definitions.backend.models.schema.EventSchema, which is not exported to it",
            "  at products/visual_review/backend/logic/shadow_schema.py:1  [team-devex]",
            "  why: Code outside a product must use the product only through its facade. A name from inside the product makes a coupling that the owners of the product cannot see.",
            "  fix (safe): If the facade of the product exports the same object, import it from the facade.",
            "  fix (needs care): If the code belongs to the product, move it into the product.",
            "  needs a person: If the facade must export a new name, stop and tell the person. The owners of the product decide what its facade exports.",
            "  see: hoglint explain public-surface",
            "Fix each finding, or stop and tell the person. Do not edit hoglint.ledger, hoglint.exceptions.toml, hoglint.toml or a preset to make this check pass.",
            f"2 {REST}",
            "hoglint blocks findings on the lines this commit changes. Fix them, or run `hoglint explain public-surface`.",
        ]

    def test_debt_in_a_touched_file_off_the_changed_lines_passes(self) -> None:
        assert hook(fixture("touched.out"), diff_of("touched.diff", PROBE), [PROBE]) == (0, f"3 {REST}")

    @parameterized.expand([("non_ascii_name", CAFE, "caf"), ("name_with_a_space", SPACE, "space probe")])
    def test_a_finding_in_an_unusual_path_blocks(self, _name: str, path: str, header: str) -> None:
        code, text = hook(fixture("names.out"), diff_of("names.diff", header), [path])
        assert code == 1
        assert f"  at {path}:1  [team-devex]" in text.splitlines()

    @parameterized.expand([("with_other_files", [PLAIN, LEDGER], 1), ("alone", [LEDGER], 0)])
    def test_new_ledger_lines_block_only_with_other_files(self, _name: str, staged: list[str], expected: int) -> None:
        code, text = hook(fixture("ledger.out"), fixture("ledger.diff"), staged)
        assert code == expected
        assert "This change adds 3 lines to hoglint.ledger, with no policy change." in text.splitlines()

    @parameterized.expand([("with_other_files", [EXCEPTIONS, PLAIN], 1), ("alone", [EXCEPTIONS], 0)])
    def test_a_new_exception_blocks_only_with_other_files(self, _name: str, staged: list[str], expected: int) -> None:
        code, _text = hook("hoglint: no new problems.\n", fixture("exception.diff"), staged, status=0)
        assert code == expected

    def test_output_that_is_not_a_report_lets_the_commit_continue(self) -> None:
        code, text = hook("", "", [PLAIN], 2, fixture("config-error.err"))
        assert code == 0
        assert text.splitlines() == ["config error:", "  bogus: unknown section  [hoglint.toml]", CONTINUES]

    def test_a_stray_line_inside_the_findings_cuts_no_row(self) -> None:
        second_finding = "  public-surface: products.visual_review.backend.logic.shadow_probe names products.event_definitions.backend.models.property_definition"
        output = with_lines(fixture("touched.out"), second_finding, [MEMO_FILL])
        code, text = hook(output, fixture("touched.diff"), [PROBE, SCHEMA])
        assert code == 1
        assert "  at products/visual_review/backend/logic/shadow_schema.py:1  [team-devex]" in text.splitlines()

    def test_extractor_unknowns_and_rows_without_a_place_are_printed_and_counted(self) -> None:
        # No real run produced these two rows. They follow hoglint 0.2.2's format strings in
        # report.py: `unknown_line` with the extractor cause, and `place` for a finding with no path.
        no_place = [
            "  public-surface: products.visual_review.backend.logic names products.event_definitions.backend.models, which is not exported to it",
            "    at (no line)  [team-devex]",
        ]
        extractor = f"  get-model [extractor, not-modelled] {SCHEMA}:1: model-label 'apps.get_model' did not resolve"
        output = with_lines(fixture("touched.out"), "advisory rows (898)", no_place)
        output = with_lines(output, "unknowns attributed against", [extractor])
        code, text = hook(output, fixture("touched.diff"), [PROBE, SCHEMA])
        assert code == 1
        assert "  at (no line)  [team-devex]" in text.splitlines()
        assert extractor[2:] in text.splitlines()
        assert f"4 {REST}" in text.splitlines()


class TestShadowReport:
    def test_annotates_only_rows_on_the_lines_the_pull_request_changes(self) -> None:
        report = ShadowReport(fixture("touched.out"), "", 1, "Tuesday, Nov 24", fixture("touched.diff"))
        assert report.annotations() == [
            "::warning file=products/visual_review/backend/logic/shadow_schema.py,line=1,title=hoglint public-surface (shadow)::products.visual_review.backend.logic.shadow_schema names products.event_definitions.backend.models.schema.EventSchema, which is not exported to it"
        ]
        assert [row.place() for row in report.other_rows()] == [f"{PROBE}:1", f"{PROBE}:2"]
        assert "Advisory rows, which never block: 898." in report.summary()

    def test_the_summary_says_when_hoglint_did_not_run(self) -> None:
        report = ShadowReport("", fixture("config-error.err"), 2, "Tuesday, Nov 24", "")
        assert report.annotations() == []
        assert "hoglint did not run (exit 2): config error: bogus: unknown section  [hoglint.toml]" in report.summary()

    def test_the_summary_shows_the_pull_request_s_own_sections_from_compare(self) -> None:
        report = ShadowReport(fixture("compare.out"), "", 1, "Tuesday, Nov 24", fixture("compare.diff"))
        summary = report.summary().split("**Not on lines this PR changes")[0]
        assert "findings new (2)" in summary
        assert "code growth (fails) (2)" in summary


class TestChangedLines:
    def test_reads_a_quoted_non_ascii_path_and_a_path_with_a_space(self) -> None:
        assert {CAFE, SPACE} <= ChangedLines.of(fixture("names.diff")).new_files


class TestOldToolEdits:
    def test_notes_only_edits_to_files_that_go_away(self) -> None:
        pyproject_diff = '@@ -640,6 +640,7 @@ ignore_imports = [\n+    "products.example.backend.facade.api -> products.example.backend.models",\n'
        edits = OldToolEdits(
            ["products/visual_review/backend/models.py", "tach.toml", "pyproject.toml"],
            pyproject_diff,
            "Tuesday, Nov 24",
        )
        assert edits.paths() == ["tach.toml", "pyproject.toml"]

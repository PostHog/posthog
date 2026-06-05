import os
from pathlib import Path

from posthog.test.base import BaseTest

from posthog.hogql.printer.test.property_corpus import LOGICAL_CASES
from posthog.hogql.printer.test.property_harness import compile_case, normalize

GOLDEN_DIR = Path(__file__).parent / "__golden__"
GOLDEN_FILE = GOLDEN_DIR / "property_corpus_logical.golden.sql"

UPDATE_ENV = "UPDATE_PROPERTY_GOLDEN"

_HEADER = (
    "# Golden output for the HogQL property-handling characterization corpus (logical cases).\n"
    "# Harness-owned (NOT a .ambr snapshot) — regenerate with `UPDATE_PROPERTY_GOLDEN=1 hogli test <this file>`.\n"
    "# Locks the MASTER logical-access rendering across dialects; team-id literals normalized to <TEAM>.\n"
    "# Text churn here from a result-equivalent rewrite is reviewed per-PR, not auto-accepted (doc §8.7/§12.6).\n"
)


class TestPropertyGolden(BaseTest):
    """Compiles every logical corpus case across the dialects it supports and pins the printed SQL to a golden file.

    This is the cross-dialect tripwire for the printer rearchitecture: logical property access must keep rendering the
    same way as physical optimization moves out of the printer. The golden is generated at MASTER behavior; a diff is a
    signal to review, not necessarily a regression (result-equivalent rewrites are expected — the execution + skip-index
    net is the correctness gate).
    """

    def _render_corpus(self) -> str:
        blocks: list[str] = [_HEADER]
        for case in LOGICAL_CASES:
            block = [f"#### {case.name}  —  {case.description}", f"## hogql-source: {case.sql}"]
            for dialect in case.dialects:
                printed, _ = compile_case(case.sql, dialect, self.team, case.modifiers)
                block.append(f"-- {dialect}")
                block.append(normalize(printed, self.team))
            blocks.append("\n".join(block))
        return "\n\n".join(blocks) + "\n"

    def test_logical_corpus_matches_golden(self) -> None:
        rendered = self._render_corpus()

        if os.environ.get(UPDATE_ENV):
            GOLDEN_DIR.mkdir(exist_ok=True)
            GOLDEN_FILE.write_text(rendered)
            self.skipTest(f"Wrote golden to {GOLDEN_FILE} ({UPDATE_ENV} set)")

        assert GOLDEN_FILE.exists(), f"Golden file missing; generate it with {UPDATE_ENV}=1"
        expected = GOLDEN_FILE.read_text()
        assert rendered == expected, (
            f"Logical property corpus diverged from golden ({GOLDEN_FILE}).\n"
            f"If this is an intended result-equivalent change, regenerate with {UPDATE_ENV}=1 and review the diff."
        )

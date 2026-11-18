from hoglint_shadow import OldToolEdits, ShadowReport
from parameterized import parameterized

# Real output of `hoglint compare --base HEAD^1` (hoglint 0.2.1) on a commit that added two imports
# past another product's facade.
COMPARE_TWO_FINDINGS = """\
hoglint compare: the change fails: 2 growth keys grew from code.
base summary: the stored summary hoglint-summary-p6-283ef7dba8c040b13136810727d538dc lacks the group edges compare lists, so the full base scan ran
code growth (fails) (2)
  public-surface products.event_definitions.backend.models.event_definition.EventDefinition import visual_review: 0 -> 1
  public-surface products.event_definitions.backend.models.property_definition.PropertyDefinition import visual_review: 0 -> 1
counts: findings new 2, resolved 0; ledger lines added 0, removed 0; zero-net swaps 0; rule growth 0; new group edges 2; old unknowns 138. Show every section: hoglint compare --base HEAD^1 --all.

hoglint: this commit is blocked: 2 new findings.
New findings by rule:
     2  public-surface
Fix each finding, or stop and tell the person. Do not edit hoglint.ledger, hoglint.exceptions.toml, hoglint.toml or a preset to make this check pass.

The first finding of each rule (1 of 2 findings):
public-surface: products.visual_review.backend.logic.shadow_probe names products.event_definitions.backend.models.event_definition.EventDefinition, which is not exported to it
  at products/visual_review/backend/logic/shadow_probe.py:1  [team-devex]
  why: Code outside a product must use the product only through its facade. A name from inside the product makes a coupling that the owners of the product cannot see.
  fix (safe): If the facade of the product exports the same object, import it from the facade.
  fix (needs care): If the code belongs to the product, move it into the product.
  needs a person: If the facade must export a new name, stop and tell the person. The owners of the product decide what its facade exports.
  see: hoglint explain public-surface

More findings:
public-surface: products.visual_review.backend.logic.shadow_probe names products.event_definitions.backend.models.property_definition.PropertyDefinition, which is not exported to it
  at products/visual_review/backend/logic/shadow_probe.py:2  [team-devex]

Not shown: 898 advisory rows, 138 old unknowns, 10145 old findings in the ledger. Show every row: hoglint compare --base HEAD^1 --all. Show one rule: hoglint compare --base HEAD^1 --rule <rule>.
What the hook checks and what to do: hoglint help hook.
"""

# Real output of `hoglint check` (hoglint 0.2.1) on a tree with nothing new.
CHECK_NO_FINDINGS = """\
hoglint: no new problems (898 advisory rows, 138 old unknowns, 10145 old findings in the ledger).
"""

PYPROJECT_IMPORT_LINTER_DIFF = """\
@@ -640,6 +640,7 @@ ignore_imports = [
     "products.example.backend.facade.api -> products.example.backend.logic",
+    "products.example.backend.facade.api -> products.example.backend.models",
 ]
"""


class TestShadowReport:
    @parameterized.expand(
        [
            (
                "compare_with_two_findings",
                COMPARE_TWO_FINDINGS,
                [
                    "::warning file=products/visual_review/backend/logic/shadow_probe.py,line=1,title=hoglint public-surface (shadow)::products.visual_review.backend.logic.shadow_probe names products.event_definitions.backend.models.event_definition.EventDefinition, which is not exported to it",
                    "::warning file=products/visual_review/backend/logic/shadow_probe.py,line=2,title=hoglint public-surface (shadow)::products.visual_review.backend.logic.shadow_probe names products.event_definitions.backend.models.property_definition.PropertyDefinition, which is not exported to it",
                ],
            ),
            ("check_with_no_findings", CHECK_NO_FINDINGS, []),
        ]
    )
    def test_annotates_each_finding_with_a_place(self, _name: str, output: str, expected: list[str]) -> None:
        assert ShadowReport(output, "Tuesday, Nov 24").annotations() == expected


class TestOldToolEdits:
    def test_notes_only_edits_to_files_that_go_away(self) -> None:
        edits = OldToolEdits(
            ["products/visual_review/backend/models.py", "tach.toml", "pyproject.toml"],
            PYPROJECT_IMPORT_LINTER_DIFF,
            "Tuesday, Nov 24",
        )
        assert edits.paths() == ["tach.toml", "pyproject.toml"]

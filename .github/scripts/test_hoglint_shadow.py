from hoglint_shadow import HookFilter, OldToolEdits, ShadowReport
from parameterized import parameterized

# Real output of `hoglint check --index --all` (hoglint 0.2.2). HEAD carries the two
# shadow_probe.py findings, as master does when CI lets them through, and shadow_schema.py is
# staged. Every line is verbatim; the advisory and unknown lists are cut to their first rows.
CHECK_INDEX_ALL = """\
hoglint: this commit is blocked: 3 new findings.
New findings by rule:
     3  public-surface
Fix each finding, or stop and tell the person. Do not edit hoglint.ledger, hoglint.exceptions.toml, hoglint.toml or a preset to make this check pass.
new findings (3)
  public-surface: products.visual_review.backend.logic.shadow_probe names products.event_definitions.backend.models.event_definition.EventDefinition, which is not exported to it
    at products/visual_review/backend/logic/shadow_probe.py:1  [team-devex]
    why: Code outside a product must use the product only through its facade. A name from inside the product makes a coupling that the owners of the product cannot see.
    fix (safe): If the facade of the product exports the same object, import it from the facade.
    fix (needs care): If the code belongs to the product, move it into the product.
    needs a person: If the facade must export a new name, stop and tell the person. The owners of the product decide what its facade exports.
    see: hoglint explain public-surface
  public-surface: products.visual_review.backend.logic.shadow_probe names products.event_definitions.backend.models.property_definition.PropertyDefinition, which is not exported to it
    at products/visual_review/backend/logic/shadow_probe.py:2  [team-devex]
  public-surface: products.visual_review.backend.logic.shadow_schema names products.event_definitions.backend.models.schema.EventSchema, which is not exported to it
    at products/visual_review/backend/logic/shadow_schema.py:1  [team-devex]
advisory rows (898)
  request-path: ee.settings reaches products.actions.backend.facade.api.find_action_team_id: ee.settings -> posthog.middleware.AuthenticationMiddleware -> products.actions.backend.facade.api.find_action_team_id
    at ee/settings.py:64
unknowns (137)
  get-model [inherited, not-modelled] posthog/admin/console/organization_deletion_panels.py:64: model-label 'apps.get_model' did not resolve
  get-model [inherited, not-modelled] posthog/api/file_system/access_levels.py:134: model-label 'apps.get_model' did not resolve
unknowns attributed against HEAD (tree 950572c39e2a, stored summary): 0 introduced, 0 ambiguous, 137 inherited
level isolated: 25 pass, 74 fail
10145 findings accepted by the ledger
What the hook checks and what to do: hoglint help hook.
"""

STAGED_PROBE = "products/visual_review/backend/logic/shadow_schema.py"

REST_OF_MASTER = (
    "3 findings in files you do not commit came from master; the ledger catches up there. "
    "Full list: hoglint check --index --all."
)

PYPROJECT_IMPORT_LINTER_DIFF = """\
@@ -640,6 +640,7 @@ ignore_imports = [
     "products.example.backend.facade.api -> products.example.backend.logic",
+    "products.example.backend.facade.api -> products.example.backend.models",
 ]
"""


class TestHookFilter:
    def test_a_finding_in_a_staged_file_blocks_with_its_rule_guidance(self) -> None:
        code, text = HookFilter(CHECK_INDEX_ALL, {STAGED_PROBE}).verdict()
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
            "2 findings in files you do not commit came from master; the ledger catches up there. Full list: hoglint check --index --all.",
            "hoglint blocks findings in the files you commit. Fix them, or run `hoglint explain public-surface`.",
        ]

    @parameterized.expand(
        [
            ("only_master_findings", {"products/visual_review/backend/logic/shadow_clean.py"}),
            ("advisory_and_inherited_rows", {"ee/settings.py", "posthog/api/file_system/access_levels.py"}),
        ]
    )
    def test_rows_outside_the_staged_files_pass_as_one_count(self, _name: str, staged: set[str]) -> None:
        assert HookFilter(CHECK_INDEX_ALL, staged).verdict() == (0, REST_OF_MASTER)


class TestShadowReport:
    def test_annotates_only_the_rows_in_files_the_pull_request_changes(self) -> None:
        report = ShadowReport(CHECK_INDEX_ALL, "Tuesday, Nov 24", {STAGED_PROBE})
        assert report.annotations() == [
            "::warning file=products/visual_review/backend/logic/shadow_schema.py,line=1,title=hoglint public-surface (shadow)::products.visual_review.backend.logic.shadow_schema names products.event_definitions.backend.models.schema.EventSchema, which is not exported to it"
        ]
        assert [row.place() for row in report.master_rows()] == [
            "products/visual_review/backend/logic/shadow_probe.py:1",
            "products/visual_review/backend/logic/shadow_probe.py:2",
        ]
        summary = report.summary()
        assert "Advisory rows, which never block: 898." in summary
        assert "request-path" not in summary


class TestOldToolEdits:
    def test_notes_only_edits_to_files_that_go_away(self) -> None:
        edits = OldToolEdits(
            ["products/visual_review/backend/models.py", "tach.toml", "pyproject.toml"],
            PYPROJECT_IMPORT_LINTER_DIFF,
            "Tuesday, Nov 24",
        )
        assert edits.paths() == ["tach.toml", "pyproject.toml"]

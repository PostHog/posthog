import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from parameterized import parameterized

from products.authz.backend.logic.model_builder import (
    SOURCE_DIR,
    ModelBuilder,
    ModelRules,
    ModelSourceError,
    parse_types,
    read_test_files,
)

NOTEBOOK = "type notebook extends object\n  relations\n{statements}"
NOTEBOOK_TESTS = "name: Notebook\nmodel_file: ../../generated/model.fga\ntests: []\n"
WHY = "    # A test relation.\n"
DASHBOARD = "resources/dashboard.fga"


class TestModelRules(SimpleTestCase):
    def test_checked_in_model_follows_the_rules(self) -> None:
        self.assertEqual(ModelRules.load().problems(), [])

    @parameterized.expand(
        [
            (
                "permission_without_action",
                {
                    "resources/notebook.fga": (
                        None,
                        NOTEBOOK.format(statements=WHY + "    define can_publish: can_edit\n"),
                    )
                },
                "notebook.can_publish: there is no SDK Action",
            ),
            (
                "define_reuses_an_inherited_name",
                {DASHBOARD: (None, WHY + "    define can_edit: editor\n")},
                "already defines it",
            ),
            (
                "override_a_level",
                {
                    DASHBOARD: (
                        None,
                        WHY + "    override viewer: member from project\n",
                    )
                },
                "only permissions",
            ),
            ("remove_a_stored_relation", {DASHBOARD: (None, WHY + "    remove creator\n")}, "only permissions"),
            ("remove_a_used_permission", {DASHBOARD: (None, WHY + "    remove can_edit\n")}, "still uses it"),
            (
                "statement_without_why",
                {
                    DASHBOARD: (
                        None,
                        "    define reviewer: [organization_member#user]\n",
                    )
                },
                "add a comment above reviewer",
            ),
            (
                "extends_an_object_type",
                {"resources/insight.fga": ("extends shareable_object", "extends dashboard")},
                "must extend one of the bases",
            ),
            (
                "type_name_differs_from_file",
                {"resources/notebook.fga": (None, "type notebooks extends object\n  relations\n")},
                "named 'notebook' after the file",
            ),
            (
                "unknown_resource_type",
                {"resources/spline_reticulator.fga": (None, "type spline_reticulator extends object\n  relations\n")},
                "not a ResourceType value",
            ),
            (
                "resource_without_tests",
                {"resources/notebook.fga": (None, NOTEBOOK.format(statements=""))},
                "resources/notebook.fga.yaml is missing",
            ),
            (
                "untested_permission",
                {
                    "resources/notebook.fga": (None, NOTEBOOK.format(statements="")),
                    "resources/notebook.fga.yaml": (None, NOTEBOOK_TESTS),
                },
                "notebook.can_view: resources/notebook.fga.yaml has no check that expects true",
            ),
            (
                "unwritten_stored_relation",
                {
                    "resources/notebook.fga": (None, NOTEBOOK.format(statements="")),
                    "resources/notebook.fga.yaml": (None, NOTEBOOK_TESTS),
                },
                "notebook.creator: no tuple in resources/notebook.fga.yaml",
            ),
            (
                "unused_relation",
                {
                    "resources/notebook.fga": (
                        None,
                        NOTEBOOK.format(statements=WHY + "    define reviewer: [organization_member#user]\n"),
                    )
                },
                "notebook.reviewer: no permission",
            ),
            ("hand_edited_model", {}, "does not match its sources"),
        ]
    )
    def test_reports_a_model_that_breaks_a_rule(
        self, _name: str, edits: dict[str, tuple[str | None, str]], expected: str
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_dir = Path(directory)
            shutil.copytree(SOURCE_DIR, source_dir, dirs_exist_ok=True)
            (source_dir / "resources/notebook.fga").unlink(missing_ok=True)
            (source_dir / "resources/notebook.fga.yaml").unlink(missing_ok=True)
            original_model = ModelBuilder(source_dir).build()
            for relative_path, (old, new) in edits.items():
                path = source_dir / relative_path
                if old is None:
                    path.write_text(path.read_text() + new if path.exists() else new)
                else:
                    self.assertIn(old, path.read_text())
                    path.write_text(path.read_text().replace(old, new, 1))
            builder = ModelBuilder(source_dir)
            try:
                model = builder.build()
            except ModelSourceError:
                model = original_model
            if not edits:
                model = model.replace("define can_view: viewer", "define can_view: viewer or creator", 1)
            rules = ModelRules(
                model=model,
                builder=builder,
                json_relations={definition.name: definition.relation_names() for definition in parse_types(model)},
                tests=read_test_files(builder),
            )

            problems = rules.problems()

        self.assertTrue(any(expected in problem for problem in problems), problems)

    def test_build_refuses_to_overwrite_a_hand_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.fga"
            builder = ModelBuilder()
            builder.write(model_path)
            model_path.write_text(model_path.read_text().replace("define can_view: viewer", "define can_view: creator"))

            with self.assertRaises(ModelSourceError):
                builder.write(model_path)
            builder.write(model_path, force=True)

            self.assertEqual(model_path.read_text(), builder.build())

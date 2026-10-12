import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

import yaml
from parameterized import parameterized

from products.authz.backend.logic.model_builder import (
    MODEL_TESTS_PATH,
    SOURCE_DIR,
    ModelBuilder,
    ModelRules,
    ModelSourceError,
    assertions_from_tests,
    parse_types,
)

NOTEBOOK_WITH = '\n[notebook]\n\n[notebook.relations.{name}]\ndefinition = "{definition}"\nwhy = "A test relation."\n'


class TestModelRules(SimpleTestCase):
    def test_checked_in_model_follows_the_rules(self) -> None:
        self.assertEqual(ModelRules.load().problems(), [])

    @parameterized.expand(
        [
            (
                "core_type_grows",
                "core.fga",
                "    define assignee:",
                "    define reviewer: [user]\n    define assignee:",
                "[core_relations] role",
            ),
            (
                "permission_without_action",
                "resources.toml",
                "",
                NOTEBOOK_WITH.format(name="can_publish", definition="editor"),
                "[unmapped_permissions] notebook",
            ),
            (
                "resource_change_without_limit",
                "resources.toml",
                "",
                NOTEBOOK_WITH.format(name="can_delete", definition="manager"),
                "[resource_relations] notebook",
            ),
            (
                "complex_resource_relation",
                "resources.toml",
                "",
                NOTEBOOK_WITH.format(name="can_view", definition="viewer but not creator"),
                "[complex_resource_relations] notebook",
            ),
            (
                "unused_relation",
                "resources.toml",
                "",
                NOTEBOOK_WITH.format(name="reviewer", definition="[organization_member#user]"),
                "notebook.reviewer: no permission",
            ),
            (
                "resource_replaces_a_level",
                "resources.toml",
                "",
                NOTEBOOK_WITH.format(name="viewer", definition="member from project"),
                "can replace only template permissions",
            ),
            ("unknown_resource_type", "resources.toml", "", "\n[spline_reticulator]\n", "not a ResourceType value"),
            (
                "hand_edited_model",
                "model.fga",
                "define can_view: viewer",
                "define can_view: viewer or creator",
                "does not match its sources",
            ),
        ]
    )
    def test_reports_a_model_that_breaks_a_rule(
        self, _name: str, file_name: str, old: str, new: str, expected: str
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_dir = Path(directory)
            shutil.copytree(SOURCE_DIR, source_dir, dirs_exist_ok=True)
            original_model = ModelBuilder(source_dir).build()
            if file_name != "model.fga":
                source = source_dir / file_name
                source.write_text(source.read_text().replace(old, new, 1) if old else source.read_text() + new)
            builder = ModelBuilder(source_dir)
            try:
                model = builder.build()
            except ModelSourceError:
                model = original_model
            if file_name == "model.fga":
                model = model.replace(old, new, 1)
            rules = ModelRules(
                model=model,
                builder=builder,
                json_relations={definition.name: definition.relation_names() for definition in parse_types(model)},
                assertions=assertions_from_tests(yaml.safe_load(MODEL_TESTS_PATH.read_text())),
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

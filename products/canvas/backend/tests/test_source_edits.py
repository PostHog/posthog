from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.canvas.backend.source import CANVAS_ENTRY_HTML
from products.canvas.backend.source_edits import apply_source_edits
from products.canvas.backend.tests.test_source import project

EDIT_SOURCE = "function Card() {\n  return (\n    <div>\n      <Title>Users</Title>\n      <Title>Users</Title>\n    </div>\n  );\n}\n"


def replace(old: str, new: str, **extra: Any) -> dict[str, Any]:
    return {"op": "str_replace", "path": "src/card.tsx", "old_string": old, "new_string": new, **extra}


class TestApplySourceEdits(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "unique_exact_match",
                [replace("function Card() {", "function Panel() {")],
                EDIT_SOURCE.replace("function Card() {", "function Panel() {"),
            ),
            (
                "replace_all",
                [replace("Users", "People", replace_all=True)],
                EDIT_SOURCE.replace("Users", "People"),
            ),
            (
                "trailing_whitespace_and_crlf_ignored",
                [replace("  return (  \r\n    <div>\r\n", "  return (\n    <section>\n")],
                EDIT_SOURCE.replace("    <div>", "    <section>"),
            ),
            (
                "dropped_indentation_is_restored",
                [replace("return (\n  <div>", "return (\n  <main>")],
                EDIT_SOURCE.replace("    <div>", "    <main>"),
            ),
            (
                "later_operation_sees_earlier_one",
                [replace("Card", "Panel"), replace("function Panel", "export function Panel")],
                EDIT_SOURCE.replace("function Card", "export function Panel"),
            ),
        ]
    )
    def test_str_replace_applies(self, _name, operations, expected):
        edited, diagnostics = apply_source_edits(project(files={"src/card.tsx": EDIT_SOURCE}), operations)
        assert diagnostics == []
        assert edited["files"]["src/card.tsx"] == expected

    @parameterized.expand(
        [
            ("exact_duplicate", [replace("<Title>Users</Title>", "<Title>People</Title>")], "edit_ambiguous_match", 4),
            ("loose_duplicate", [replace("<Title>Users</Title>  ", "x")], "edit_ambiguous_match", 4),
            ("no_match_points_at_closest_line", [replace("return [", "return (")], "edit_no_match", 2),
            ("missing_file", [{**replace("a", "b"), "path": "src/nope.tsx"}], "edit_target_missing", None),
            (
                "rename_onto_existing_file",
                [{"op": "rename", "path": "src/card.tsx", "new_path": CANVAS_ENTRY_HTML}],
                "edit_target_exists",
                None,
            ),
        ]
    )
    def test_edit_that_cannot_apply_once_is_rejected(self, _name, operations, expected_code, expected_line):
        original = project(files={"src/card.tsx": EDIT_SOURCE})
        edited, diagnostics = apply_source_edits(original, operations)
        assert [entry["code"] for entry in diagnostics] == [expected_code]
        assert diagnostics[0].get("line") == expected_line
        assert original["files"]["src/card.tsx"] == EDIT_SOURCE

    def test_replace_all_that_would_exceed_the_file_limit_is_rejected(self) -> None:
        source = "a\n" * 200_000
        original = project(files={"src/card.tsx": source})
        edited, diagnostics = apply_source_edits(original, [replace("a", "x" * 4096, replace_all=True)])
        assert [entry["code"] for entry in diagnostics] == ["edit_too_large"]
        assert edited["files"]["src/card.tsx"] == source

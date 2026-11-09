from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.scope_docs import ScopeDependency, ScopeDoc, collect_scope_docs

VALID: dict[str, Any] = {
    "object": "insight",
    "name": "Insight",
    "plural": "insights",
    "description": "Insights and their results.",
    "group": "Product analytics",
}


class TestScopeDoc(SimpleTestCase):
    @parameterized.expand(
        [
            ("blank_name", {"name": " "}),
            ("blank_plural", {"plural": ""}),
            ("unknown_action", {"actions": ("read", "delete")}),
            ("no_actions", {"actions": ()}),
            ("no_final_period", {"description": "Insights and their results"}),
            ("long_description", {"description": "x" * 120 + "."}),
            ("em_dash", {"description": "Insights — and their results."}),
            ("docs_off_site", {"docs_url": "https://example.com/docs/insights"}),
            ("unknown_group", {"group": "Insights"}),
            (
                "write_requires_without_write",
                {"actions": ("read",), "write_requires": ScopeDependency(scope="feature_flag:write", reason="Why.")},
            ),
            (
                "write_requires_unknown_scope",
                {"write_requires": ScopeDependency(scope="feature_flag:delete", reason="Why.")},
            ),
        ]
    )
    def test_rejects_an_invalid_declaration(self, _name: str, override: dict[str, Any]) -> None:
        with self.assertRaises(ValueError):
            ScopeDoc(**{**VALID, **override})

    def test_refuses_an_object_declared_twice(self) -> None:
        doc = ScopeDoc(**VALID)

        with self.assertRaisesRegex(ValueError, "declared more than once"):
            collect_scope_docs([[doc], [doc]])

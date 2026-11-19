from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.hogql.query import execute_hogql_query


class TestWithIcon(BaseTest):
    @parameterized.expand(
        [
            (
                "named_icon",
                "SELECT withIcon('Claude Code', 'Claude')",
                ("__hx_tag", "BrandMarkLabel", "label", "Claude Code", "mark", "Claude"),
            ),
            (
                "image_url",
                "SELECT <img src='https://example.com/logo.png' alt='Customer logo' width={24} height={16} />",
                (
                    "__hx_tag",
                    "img",
                    "src",
                    "https://example.com/logo.png",
                    "alt",
                    "Customer logo",
                    "width",
                    24,
                    "height",
                    16,
                ),
            ),
            (
                "svg_data",
                "SELECT <img src='data:image/svg+xml,%3Csvg/%3E' />",
                ("__hx_tag", "img", "src", "data:image/svg+xml,%3Csvg/%3E"),
            ),
        ]
    )
    def test_explicit_image_in_query_result(self, _name: str, query: str, expected: tuple[str | int, ...]) -> None:
        response = execute_hogql_query(query, self.team)

        self.assertEqual(response.results[0][0], expected)

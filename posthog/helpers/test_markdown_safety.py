import pytest

from django.test import SimpleTestCase

from markdown_it import MarkdownIt
from parameterized import parameterized

from posthog.helpers.markdown_safety import strip_external_links_markdown


class TestStripExternalLinks(SimpleTestCase):
    @parameterized.expand(
        [
            ("encoded", "[source]: h&#116;tps://example.com/report", []),
            ("image_before_reference", "![](https://posthog.com)[source]: h&#116;tps://example.com/report", []),
            (
                "unicode_line_separator",
                "\u2028\n\n[source]: h&#116;tps://example.com/report\n[safe]: https://posthog.com/docs",
                [],
            ),
            (
                "carriage_returns",
                "[source]: https://posthog.com/docs\r\n[safe]: https://posthog.com/",
                ["https://posthog.com/docs"],
            ),
            ("duplicate", "[source]: h&#116;tps://example.com/one\n[source]: h&#116;tps://example.com/two", []),
            (
                "posthog",
                "[source]: https://posthog.com/docs?topic=reports#slack",
                ["https://posthog.com/docs?topic=reports#slack"],
            ),
            (
                "instance",
                "[source]: https://reports.example.com/report?view=weekly#traffic",
                ["https://reports.example.com/report?view=weekly#traffic"],
            ),
        ]
    )
    def test_reference_links_use_resolved_destinations(self, _name: str, definitions: str, expected: list[str]) -> None:
        markdown = f"[Open report][source]\n\n{definitions}\n"
        filtered = strip_external_links_markdown(markdown, additional_allowed_origin="https://reports.example.com/")
        destinations = [
            child.attrGet("href")
            for token in MarkdownIt("commonmark").parse(filtered)
            for child in token.children or []
            if child.type == "link_open"
        ]
        self.assertEqual(destinations, expected)

    @parameterized.expand(
        [
            ("instance", "http://localhost:8010/report", True),
            ("other_port", "http://localhost:8011/report", False),
            ("other_scheme", "https://localhost:8010/report", False),
            ("hostname_suffix", "http://localhost.example.com:8010/report", False),
            ("userinfo", "http://localhost:8010@evil.example/report", False),
            ("external", "https://example.com/report", False),
        ]
    )
    def test_configured_origin_only_preserves_matching_named_links(self, _name: str, url: str, allowed: bool) -> None:
        markdown = f"[Report]({url})"
        self.assertEqual(
            strip_external_links_markdown(markdown, additional_allowed_origin="http://localhost:8010/"),
            markdown if allowed else "Report",
        )
        self.assertEqual(strip_external_links_markdown(markdown), "Report")

    @parameterized.expand(
        [
            ("[Open [report]](h&#116;tps://example.com/report)", []),
            ("[Open [report]](https://posthog.com/docs)", ["https://posthog.com/docs"]),
            ("> [Open [report]](h&#116;tps://example.com/report)", []),
            ("- [Open [report]](h&#116;tps://example.com/report)", []),
        ]
    )
    def test_nested_link_labels_follow_url_policy(self, markdown: str, expected: list[str]) -> None:
        filtered = strip_external_links_markdown(markdown)
        links = [
            child.attrGet("href")
            for token in MarkdownIt("commonmark").parse(filtered)
            for child in token.children or []
            if child.type == "link_open"
        ]
        assert links == expected

    @parameterized.expand([("*",), ("**",), ("***",), ("_",), ("__",), ("___",), ("~~",)])
    def test_formatted_url_preserves_emphasis(self, marker: str) -> None:
        url = "https://example.com/weekly_report?period=current_week"
        self.assertEqual(
            strip_external_links_markdown(f"{marker}{url}{marker}: **42** views"),
            f"{marker}`{url}`{marker}: **42** views",
        )

    def test_adjacent_formatted_urls_remain_inert(self) -> None:
        self.assertEqual(
            strip_external_links_markdown("**https://example.com/one**https://example.com/two"),
            "**`https://example.com/one`**`https://example.com/two`",
        )

    @parameterized.expand(
        [
            ("no_title", "[x](https://evil.example.com)"),
            ("double_quote_title", '[x](https://evil.example.com "t")'),
            ("single_quote_title", "[x](https://evil.example.com 't')"),
            ("paren_title", "[x](https://evil.example.com (t))"),
            ("bare_url", "visit https://evil.example.com now"),
            # Whitespace before `)` is a valid CommonMark link — it must still be defanged, not
            # slip past both the link rule and the bare-URL rule.
            ("newline_before_paren", "[x](https://evil.example.com\n)"),
            ("space_before_paren", "[x](https://evil.example.com )"),
            # Not a CommonMark link, but the destination URL would otherwise survive bare after `](`.
            ("newline_mid_dest", "[x](https://evil.example.com\nmore)"),
            ("unquoted_title", "[x](https://evil.example.com/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa invalid title)"),
            # A `[` run used to cost the label class quadratic time, because the engine rescanned the
            # same suffix from every start. 32,000 of them took over three seconds.
            ("leading_bracket_run", "[" * 32000 + "](https://evil.example.com invalid title)"),
        ]
    )
    @pytest.mark.timeout(1, func_only=True)
    def test_non_posthog_urls_defanged(self, _label: str, markdown: str) -> None:
        out = strip_external_links_markdown(markdown)
        # The host must never survive as a live link — only inside an inert code span at most.
        self.assertNotIn("](https://evil.example.com", out)
        self.assertNotIn("(https://evil.example.com", out)

    def test_orphan_dest_backticks_without_adding_a_paren(self) -> None:
        # The orphan-dest rule wraps only the URL; the source markdown's own `)` balances the `(`,
        # so the defanged output must not gain a second closing paren.
        out = strip_external_links_markdown("[x](https://evil.example.com\nmore)")
        self.assertEqual(out, "[x](`https://evil.example.com`\nmore)")

    @parameterized.expand(
        [
            ("plain", "[docs](https://posthog.com/docs)"),
            ("trailing_space", "[docs](https://posthog.com/docs )"),
        ]
    )
    def test_posthog_links_preserved(self, _label: str, markdown: str) -> None:
        out = strip_external_links_markdown(markdown)
        self.assertIn("https://posthog.com/docs", out)

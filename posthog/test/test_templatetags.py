import json
from html.parser import HTMLParser
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from posthog.templatetags.posthog_filters import compact_number


class TestTemplateTags(TestCase):
    def test_compact_number(self):
        self.assertEqual(compact_number(5001), "5K")
        self.assertEqual(compact_number(5312), "5.31K")
        self.assertEqual(compact_number(5392), "5.39K")
        self.assertEqual(compact_number(2833102), "2.83M")
        self.assertEqual(compact_number(8283310234), "8.28B")


class _ScriptCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[tuple[dict[str, str | None], str]] = []
        self._attrs: dict[str, str | None] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self._attrs = dict(attrs)
            self.scripts.append((self._attrs, ""))

    def handle_data(self, data: str) -> None:
        if self._attrs is not None:
            attrs, text = self.scripts[-1]
            self.scripts[-1] = (attrs, text + data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._attrs = None


class TestHeadJsonDataBlocks(SimpleTestCase):
    def test_user_strings_round_trip_without_leaving_the_data_block(self) -> None:
        hostile = "</script><script>alert(1)</script> <!-- \u2028 \u2029 & \"quoted\" 'single' \\ -->"
        app_context = {"current_team": {"name": hostile}, "current_organization": {"name": hostile}}
        bootstrap = {"featureFlags": {hostile: True}}
        claims = {"email": {"value": hostile, "expires_at": 1, "hash": "h"}}

        html = render_to_string(
            "head.html",
            {
                "request": SimpleNamespace(csp_nonce="n0nce"),
                "js_posthog_api_key": "phc_test",
                "posthog_app_context": json.dumps(app_context, ensure_ascii=False),
                "posthog_bootstrap": json.dumps(bootstrap, ensure_ascii=False),
                "js_posthog_identity_distinct_id": "distinct",
                "js_posthog_identity_hash": "hash",
                "js_posthog_identity_claims": json.dumps(claims, ensure_ascii=False),
            },
        )

        collector = _ScriptCollector()
        collector.feed(html)
        data_blocks = {
            attrs["id"]: text for attrs, text in collector.scripts if attrs.get("type") == "application/json"
        }
        executable = [text for attrs, text in collector.scripts if attrs.get("type") != "application/json"]

        assert data_blocks.keys() == {
            "posthog-user-identity-with-flags",
            "posthog-identity-claims",
            "posthog-app-context",
        }
        for text in data_blocks.values():
            assert "<" not in text
            assert "\u2028" not in text and "\u2029" not in text
        assert json.loads(data_blocks["posthog-app-context"]) == app_context
        assert json.loads(data_blocks["posthog-user-identity-with-flags"]) == bootstrap
        assert json.loads(data_blocks["posthog-identity-claims"]) == claims
        # A breakout would add a script element that runs alert(1).
        assert not any("alert(1)" in text for text in executable)
        assert html.index('id="posthog-user-identity-with-flags"') < html.index(
            "getElementById('posthog-user-identity-with-flags')"
        )
        assert html.index('id="posthog-app-context"') < html.index("getElementById('posthog-app-context')")

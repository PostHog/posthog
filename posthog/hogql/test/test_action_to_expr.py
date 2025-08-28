from typing import Any, Optional

from posthog.test.base import BaseTest, _create_event

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import clear_locations

from posthog.models import Action


class TestActionToExpr(BaseTest):
    maxDiff = None

    def _parse_expr(self, expr: str, placeholders: Optional[dict[str, Any]] = None):
        return clear_locations(parse_expr(expr, placeholders=placeholders))

    def test_action_to_expr_autocapture_with_selector(self):
        """Test autocapture action with CSS selector"""
        _create_event(
            event="$autocapture", team=self.team, distinct_id="some_id", elements_chain='a.active.nav-link:text="text"'
        )
        action = Action.objects.create(
            team=self.team,
            steps_json=[
                {
                    "event": "$autocapture",
                    "selector": "a.nav-link.active",
                }
            ],
        )
        self.assertEqual(
            clear_locations(action_to_expr(action)),
            self._parse_expr(
                "event = '$autocapture' and {regex1}",
                {
                    "regex1": ast.And(
                        exprs=[
                            self._parse_expr(
                                "elements_chain =~ {regex}",
                                {
                                    "regex": ast.Constant(
                                        value='(^|;)a.*?\\.active\\..*?nav\\-link([-_a-zA-Z0-9\\.:"= \\[\\]\\(\\),]*?)?($|;|:([^;^\\s]*(;|$|\\s)))'
                                    )
                                },
                            ),
                            self._parse_expr("arrayCount(x -> x IN ['a'], elements_chain_elements) > 0"),
                        ]
                    ),
                },
            ),
        )
        resp = execute_hogql_query(
            parse_select("select count() from events where {prop}", {"prop": action_to_expr(action)}), self.team
        )
        self.assertEqual(resp.results[0][0], 1)

    def test_action_to_expr_pageview_url_contains(self):
        """Test pageview action with URL contains matching"""
        action = Action.objects.create(
            team=self.team,
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "https://example.com",
                    "url_matching": "contains",
                }
            ],
        )
        self.assertEqual(
            clear_locations(action_to_expr(action)),
            self._parse_expr("event = '$pageview' and properties.$current_url like '%https://example.com%'"),
        )

    def test_action_to_expr_multiple_steps_or(self):
        """Test action with multiple steps creating OR expression"""
        action = Action.objects.create(
            team=self.team,
            steps_json=[
                {
                    "event": "$pageview",
                    "url": "https://example2.com",
                    "url_matching": "regex",
                },
                {
                    "event": "custom",
                    "url": "https://example3.com",
                    "url_matching": "exact",
                },
            ],
        )
        self.assertEqual(
            clear_locations(action_to_expr(action)),
            self._parse_expr(
                "{s1} or {s2}",
                {
                    "s1": self._parse_expr("event = '$pageview' and properties.$current_url =~ 'https://example2.com'"),
                    "s2": self._parse_expr("event = 'custom' and properties.$current_url = 'https://example3.com'"),
                },
            ),
        )

    def test_action_to_expr_null_event_resolves_to_true(self):
        """Test action with null event step resolves to true"""
        action = Action.objects.create(team=self.team, steps_json=[{"event": "$pageview"}, {"event": None}])
        self.assertEqual(
            clear_locations(action_to_expr(action)),
            self._parse_expr("event = '$pageview' OR true"),
        )

    def test_action_to_expr_autocapture_href_regex(self):
        """Test autocapture action with href regex matching"""
        action = Action.objects.create(
            team=self.team,
            steps_json=[{"event": "$autocapture", "href": "https://example4.com", "href_matching": "regex"}],
        )
        self.assertEqual(
            clear_locations(action_to_expr(action)),
            self._parse_expr("event = '$autocapture' and elements_chain_href =~ 'https://example4.com'"),
        )

    def test_action_to_expr_autocapture_text_regex(self):
        """Test autocapture action with text regex matching"""
        action = Action.objects.create(
            team=self.team,
            steps_json=[{"event": "$autocapture", "text": "blabla", "text_matching": "regex"}],
        )
        self.assertEqual(
            clear_locations(action_to_expr(action)),
            self._parse_expr("event = '$autocapture' and arrayExists(x -> x =~ 'blabla', elements_chain_texts)"),
        )

    def test_action_to_expr_autocapture_text_contains(self):
        """Test autocapture action with text contains matching"""
        action = Action.objects.create(
            team=self.team,
            steps_json=[{"event": "$autocapture", "text": "blabla", "text_matching": "contains"}],
        )
        self.assertEqual(
            clear_locations(action_to_expr(action)),
            self._parse_expr("event = '$autocapture' and arrayExists(x -> x ilike '%blabla%', elements_chain_texts)"),
        )

    def test_action_to_expr_autocapture_text_exact(self):
        """Test autocapture action with text exact matching"""
        action = Action.objects.create(
            team=self.team,
            steps_json=[{"event": "$autocapture", "text": "blabla", "text_matching": "exact"}],
        )
        self.assertEqual(
            clear_locations(action_to_expr(action)),
            self._parse_expr("event = '$autocapture' and arrayExists(x -> x = 'blabla', elements_chain_texts)"),
        )

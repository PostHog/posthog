import re
from uuid import uuid4

import pytest
from posthog.test.base import BaseTest, _create_event, flush_persons_and_events

from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.web_analytics.bot_definitions import BOT_DEFINITIONS
from posthog.hogql_queries.web_analytics.bot_ua_fixtures import (
    BOT_USER_AGENTS,
    CATEGORY_TO_TRAFFIC_CATEGORY,
    CATEGORY_TO_TRAFFIC_TYPE,
)


def _find_matching_pattern(ua: str) -> str | None:
    """Simulate multiMatchAnyIndex: find first BOT_DEFINITIONS pattern that matches.

    Patterns are evaluated as regex by ClickHouse multiMatchAnyIndex at runtime,
    so we mirror that here (no `re.escape`).
    """
    for pattern in BOT_DEFINITIONS:
        if re.search(pattern, ua):
            return pattern
    return None


def _build_classification_cases() -> list[tuple[str, str, bool, str, str]]:
    """Build (ua, category, is_bot, traffic_type, traffic_category) tuples for all real UA strings."""
    cases = []
    for category, ua_list in BOT_USER_AGENTS.items():
        expected_is_bot = category != "regular_browser"
        expected_traffic_type = CATEGORY_TO_TRAFFIC_TYPE[category]
        expected_traffic_category = CATEGORY_TO_TRAFFIC_CATEGORY[category]
        for ua in ua_list:
            cases.append((ua, category, expected_is_bot, expected_traffic_type, expected_traffic_category))
    return cases


CLASSIFICATION_CASES = _build_classification_cases()


class TestBotClassificationRealUA:
    @pytest.mark.parametrize(
        "ua,category,expected_is_bot,expected_traffic_type,expected_traffic_category",
        CLASSIFICATION_CASES,
        ids=[f"{c[1]}:{c[0][:50]}" for c in CLASSIFICATION_CASES],
    )
    def test_pattern_matches_expected_category(
        self, ua: str, category: str, expected_is_bot: bool, expected_traffic_type: str, expected_traffic_category: str
    ):
        pattern = _find_matching_pattern(ua)

        if category == "regular_browser":
            assert pattern is None, f"Regular browser UA should not match any bot pattern, matched: {pattern}"
            return

        assert pattern is not None, f"Bot UA should match a pattern: {ua}"
        bot_def = BOT_DEFINITIONS[pattern]
        assert bot_def.traffic_type == expected_traffic_type, (
            f"UA '{ua[:50]}' matched pattern '{pattern}' with traffic_type '{bot_def.traffic_type}', "
            f"expected '{expected_traffic_type}'"
        )
        assert bot_def.category == expected_traffic_category, (
            f"UA '{ua[:50]}' matched pattern '{pattern}' with category '{bot_def.category}', "
            f"expected '{expected_traffic_category}'"
        )

    def test_all_bot_definitions_have_matching_ua_fixture(self):
        # Patterns that are substrings of other patterns can't have standalone UA fixtures
        # because multiMatchAnyIndex may match the shorter pattern first
        KNOWN_SUBSTRING_PATTERNS: set[str] = set()

        all_bot_uas = []
        for category, ua_list in BOT_USER_AGENTS.items():
            if category != "regular_browser":
                all_bot_uas.extend(ua_list)

        matched_patterns: set[str] = set()
        for ua in all_bot_uas:
            pattern = _find_matching_pattern(ua)
            if pattern:
                matched_patterns.add(pattern)

        unmatched = set(BOT_DEFINITIONS.keys()) - matched_patterns - KNOWN_SUBSTRING_PATTERNS
        assert not unmatched, f"BOT_DEFINITIONS patterns with no matching UA fixture: {unmatched}"


class TestTrafficTypeIntegration(BaseTest):
    def _create_tagged_event(self, tag: str, **kwargs):
        props = kwargs.pop("properties", {})
        props["_test_tag"] = tag
        _create_event(properties=props, **kwargs)

    def _query_tagged(self, select: str, tag: str, extra_where: str = ""):
        where = f"properties._test_tag = '{tag}'"
        if extra_where:
            where += f" AND {extra_where}"
        return execute_hogql_query(
            f"SELECT {select} FROM events WHERE {where} ORDER BY properties.$user_agent",
            self.team,
        )

    def test_all_real_ua_classify_correctly(self):
        tag = uuid4().hex
        all_cases = []
        for category, ua_list in BOT_USER_AGENTS.items():
            for ua in ua_list:
                all_cases.append((ua, category))

        for i, (ua, _category) in enumerate(all_cases):
            self._create_tagged_event(
                tag=tag,
                distinct_id=f"ua-{i}",
                event="test_bulk_classify",
                team=self.team,
                properties={"$user_agent": ua},
            )
        flush_persons_and_events()

        response = self._query_tagged(
            """
                properties.$user_agent as ua,
                __preview_isBot(properties.$user_agent) as is_bot,
                __preview_getTrafficType(properties.$user_agent) as traffic_type,
                __preview_getTrafficCategory(properties.$user_agent) as category,
                __preview_getBotName(properties.$user_agent) as bot_name
            """,
            tag,
        )

        results_by_ua = {row[0]: row for row in response.results}

        for ua, category in all_cases:
            row = results_by_ua.get(ua)
            assert row is not None, f"No result for UA: {ua[:60]}"
            _ua, is_bot, traffic_type, traffic_category, bot_name = row

            expected_is_bot = category != "regular_browser"
            expected_traffic_type = CATEGORY_TO_TRAFFIC_TYPE[category]
            expected_traffic_category = CATEGORY_TO_TRAFFIC_CATEGORY[category]

            assert is_bot == expected_is_bot, f"is_bot mismatch for {ua[:60]}: got {is_bot}"
            assert traffic_type == expected_traffic_type, f"traffic_type mismatch for {ua[:60]}: got {traffic_type}"
            assert traffic_category == expected_traffic_category, (
                f"traffic_category mismatch for {ua[:60]}: got {traffic_category}"
            )
            if expected_is_bot:
                assert bot_name != "", f"bot_name should not be empty for bot UA: {ua[:60]}"
            else:
                assert bot_name == "", f"bot_name should be empty for regular UA: {ua[:60]}"

    def test_virt_properties_with_raw_user_agent(self):
        tag = uuid4().hex
        self._create_tagged_event(
            tag=tag,
            distinct_id="raw-ua",
            event="test_raw_ua",
            team=self.team,
            properties={"$raw_user_agent": "Googlebot/2.1"},
        )
        flush_persons_and_events()

        response = self._query_tagged(
            "`$virt_is_bot`, `$virt_traffic_type`, `$virt_traffic_category`, `$virt_bot_name`", tag
        )
        assert len(response.results) == 1
        is_bot, traffic_type, category, bot_name = response.results[0]
        assert is_bot == 1
        assert traffic_type == "Bot"
        assert category == "search_crawler"
        assert bot_name == "Googlebot"

    def test_virt_properties_with_user_agent_fallback(self):
        tag = uuid4().hex
        self._create_tagged_event(
            tag=tag,
            distinct_id="fallback-ua",
            event="test_ua_fallback",
            team=self.team,
            properties={"$user_agent": "curl/8.0"},
        )
        flush_persons_and_events()

        response = self._query_tagged(
            "`$virt_is_bot`, `$virt_traffic_type`, `$virt_traffic_category`, `$virt_bot_name`", tag
        )
        assert len(response.results) == 1
        is_bot, traffic_type, category, bot_name = response.results[0]
        assert is_bot == 1
        assert traffic_type == "Automation"
        assert category == "http_client"
        assert bot_name == "curl"

    def test_virt_properties_raw_ua_takes_precedence(self):
        tag = uuid4().hex
        self._create_tagged_event(
            tag=tag,
            distinct_id="both-ua",
            event="test_raw_precedence",
            team=self.team,
            properties={"$raw_user_agent": "GPTBot/1.0", "$user_agent": "Mozilla/5.0 Chrome/120.0"},
        )
        flush_persons_and_events()

        response = self._query_tagged("`$virt_is_bot`, `$virt_traffic_type`, `$virt_bot_name`", tag)
        assert len(response.results) == 1
        is_bot, traffic_type, bot_name = response.results[0]
        assert is_bot == 1
        assert traffic_type == "AI Agent"
        assert bot_name == "GPTBot"

    def test_virt_properties_null_user_agent(self):
        tag = uuid4().hex
        self._create_tagged_event(tag=tag, distinct_id="no-ua", event="test_null_ua", team=self.team, properties={})
        flush_persons_and_events()

        response = self._query_tagged(
            "`$virt_is_bot`, `$virt_traffic_type`, `$virt_traffic_category`, `$virt_bot_name`", tag
        )
        assert len(response.results) == 1
        is_bot, traffic_type, category, bot_name = response.results[0]
        assert is_bot == 1
        assert traffic_type == "Automation"
        assert category == "no_user_agent"
        assert bot_name == ""

    def test_virt_properties_empty_user_agent(self):
        tag = uuid4().hex
        self._create_tagged_event(
            tag=tag,
            distinct_id="empty-ua",
            event="test_empty_ua",
            team=self.team,
            properties={"$user_agent": ""},
        )
        flush_persons_and_events()

        response = self._query_tagged("`$virt_is_bot`, `$virt_traffic_type`, `$virt_traffic_category`", tag)
        assert len(response.results) == 1
        is_bot, traffic_type, category = response.results[0]
        assert is_bot == 1
        assert traffic_type == "Automation"
        assert category == "no_user_agent"

    def test_filter_by_virt_is_bot(self):
        tag = uuid4().hex
        bot_uas = ["Googlebot/2.1", "curl/8.0", "GPTBot/1.0"]
        regular_uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15",
        ]

        for i, ua in enumerate(bot_uas + regular_uas):
            self._create_tagged_event(
                tag=tag,
                distinct_id=f"filter-{i}",
                event="test_bot_filter",
                team=self.team,
                properties={"$user_agent": ua},
            )
        flush_persons_and_events()

        response = self._query_tagged("properties.$user_agent as ua", tag, extra_where="NOT `$virt_is_bot`")
        result_uas = [row[0] for row in response.results]
        assert len(result_uas) == len(regular_uas)
        for ua in regular_uas:
            assert ua in result_uas, f"Regular UA should pass bot filter: {ua[:50]}"

    def test_group_by_virt_traffic_type(self):
        tag = uuid4().hex
        test_uas = {
            "AI Agent": "GPTBot/1.0",
            "Bot": "Googlebot/2.1",
            "Automation": "curl/8.0",
            "Regular": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
        }

        for i, (_traffic_type, ua) in enumerate(test_uas.items()):
            self._create_tagged_event(
                tag=tag,
                distinct_id=f"group-{i}",
                event="test_group_type",
                team=self.team,
                properties={"$user_agent": ua},
            )
        flush_persons_and_events()

        response = execute_hogql_query(
            f"""
            SELECT `$virt_traffic_type` as traffic_type, count() as cnt
            FROM events
            WHERE properties._test_tag = '{tag}'
            GROUP BY traffic_type
            ORDER BY traffic_type
            """,
            self.team,
        )
        results = {row[0]: row[1] for row in response.results}
        assert results == {"AI Agent": 1, "Automation": 1, "Bot": 1, "Regular": 1}

    def test_http_access_log_event(self):
        tag = uuid4().hex
        self._create_tagged_event(
            tag=tag,
            distinct_id="http-log",
            event="http_request",
            team=self.team,
            properties={
                "$user_agent": "Mozilla/5.0 (compatible; AhrefsBot/7.0; +http://ahrefs.com/robot/)",
                "method": "GET",
                "path": "/api/v1/health",
                "status_code": 200,
            },
        )
        flush_persons_and_events()

        response = self._query_tagged(
            "`$virt_is_bot`, `$virt_traffic_type`, `$virt_traffic_category`, `$virt_bot_name`", tag
        )
        assert len(response.results) == 1
        is_bot, traffic_type, category, bot_name = response.results[0]
        assert is_bot == 1
        assert traffic_type == "Bot"
        assert category == "seo_crawler"
        assert bot_name == "Ahrefs"


class TestVirtualPropertiesWithCustomEvents(BaseTest):
    def test_virt_properties_work_across_event_types(self):
        tag = uuid4().hex
        event_names = ["$pageview", "$pageleave", "$autocapture", "custom_event", "http_request", "api_call"]

        for i, event_name in enumerate(event_names):
            _create_event(
                distinct_id=f"cross-{i}",
                event=event_name,
                team=self.team,
                properties={"$user_agent": "Googlebot/2.1", "_test_tag": tag},
            )
        flush_persons_and_events()

        for event_name in event_names:
            response = execute_hogql_query(
                f"""
                SELECT `$virt_is_bot`, `$virt_traffic_type`
                FROM events WHERE properties._test_tag = '{tag}' AND event = '{event_name}'
                """,
                self.team,
            )
            assert len(response.results) == 1, f"Expected 1 result for {event_name}, got {len(response.results)}"
            is_bot, traffic_type = response.results[0]
            assert is_bot == 1, f"is_bot should be 1 for {event_name}"
            assert traffic_type == "Bot", f"traffic_type should be Bot for {event_name}"

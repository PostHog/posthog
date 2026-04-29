import re
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from posthog.hogql.compiler.bytecode import create_bytecode

from posthog.cdp.filters import (
    build_behavioral_event_expr,
    cohort_filters_to_expr,
    compile_filters_bytecode,
    hog_function_filters_to_expr,
)
from posthog.models.action.action import Action
from posthog.models.cohort.cohort import Cohort

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION


def _normalize_error(error: str) -> str:
    """Replace dynamic IDs and URLs in error messages with stable placeholders."""
    error = re.sub(r"id=\d+", "id=N", error)
    error = re.sub(r"https?://[^/]+/project/\d+/settings/project", "SETTINGS_URL", error)
    return error


class TestHogFunctionFilters(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    action: Action
    filters: dict

    def setUp(self):
        super().setUp()
        self.action = Action.objects.create(
            team=self.team,
            name="test action",
            steps_json=[{"event": "$pageview", "url": "docs", "url_matching": "contains"}],
        )

        self.team.test_account_filters = [
            {
                "key": "email",
                "value": "@posthog.com",
                "operator": "not_icontains",
                "type": "person",
            }
        ]
        self.team.save()

        self.filters = {
            "events": [
                {
                    "id": "$pageview",
                    "name": "$pageview",
                    "type": "events",
                    "order": 0,
                    "properties": [{"key": "url", "value": "docs", "operator": "icontains", "type": "event"}],
                }
            ],
            "actions": [{"id": f"{self.action.id}", "name": "Test Action", "type": "actions", "order": 1}],
            "properties": [
                {
                    "key": "email",
                    "value": "@posthog.com",
                    "operator": "icontains",
                    "type": "person",
                },
                {
                    "key": "name",
                    "value": "ben",
                    "operator": "exact",
                    "type": "person",
                },
            ],
            "filter_test_accounts": True,
        }

    def filters_to_bytecode(self, filters: dict):
        res = hog_function_filters_to_expr(filters=filters, team=self.team, actions={self.action.id: self.action})

        return json.loads(json.dumps(create_bytecode(res).bytecode))

    def test_filters_empty(self):
        bytecode = self.filters_to_bytecode(filters={})
        assert bytecode == ["_H", HOGQL_BYTECODE_VERSION, 29]
        assert execute_bytecode(bytecode, {}).result is True

    def test_filters_all_events(self):
        bytecode = self.filters_to_bytecode(
            filters={
                "events": [
                    {
                        "id": None,
                        "name": "All events",
                        "type": "events",
                        "order": 0,
                    }
                ]
            }
        )
        assert bytecode == ["_H", HOGQL_BYTECODE_VERSION, 29]

        assert execute_bytecode(bytecode, {}).result is True

    def test_filters_raises_on_select(self):
        response = compile_filters_bytecode(
            filters={
                "properties": [
                    {
                        "type": "hogql",
                        "key": "(select 1)",
                    }
                ]
            },
            team=self.team,
        )
        assert response["bytecode_error"] == "Select queries are not allowed in filters"

    def test_filters_events(self):
        bytecode = self.filters_to_bytecode(filters={"events": self.filters["events"]})
        assert bytecode == [
            "_H",
            HOGQL_BYTECODE_VERSION,
            32,
            "$pageview",
            32,
            "event",
            1,
            1,
            11,
            32,
            "%docs%",
            32,
            "url",
            32,
            "properties",
            1,
            2,
            2,
            "toString",
            1,
            18,
            3,
            2,
        ]

    def test_filters_actions(self):
        bytecode = self.filters_to_bytecode(filters={"actions": self.filters["actions"]})
        assert bytecode == [
            "_H",
            HOGQL_BYTECODE_VERSION,
            32,
            "$pageview",
            32,
            "event",
            1,
            1,
            11,
            32,
            "%docs%",
            32,
            "$current_url",
            32,
            "properties",
            1,
            2,
            17,
            3,
            2,
        ]

        # Also works if we don't pass the actions dict
        expr = hog_function_filters_to_expr(filters={"actions": self.filters["actions"]}, team=self.team, actions={})
        bytecode_2 = create_bytecode(expr).bytecode
        assert bytecode == bytecode_2

    def test_filters_properties(self):
        assert self.filters_to_bytecode(filters={"properties": self.filters["properties"]}) == [
            "_H",
            HOGQL_BYTECODE_VERSION,
            32,
            "%@posthog.com%",
            32,
            "email",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            2,
            "toString",
            1,
            18,
            32,
            "ben",
            32,
            "name",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            11,
            3,
            2,
        ]

    def test_filters_full(self):
        bytecode = self.filters_to_bytecode(filters=self.filters)
        assert bytecode == [
            "_H",
            HOGQL_BYTECODE_VERSION,
            32,
            "%@posthog.com%",
            32,
            "email",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            2,
            "toString",
            1,
            20,
            32,
            "%@posthog.com%",
            32,
            "email",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            2,
            "toString",
            1,
            18,
            32,
            "ben",
            32,
            "name",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            11,
            32,
            "$pageview",
            32,
            "event",
            1,
            1,
            11,
            32,
            "%docs%",
            32,
            "url",
            32,
            "properties",
            1,
            2,
            2,
            "toString",
            1,
            18,
            3,
            2,
            32,
            "$pageview",
            32,
            "event",
            1,
            1,
            11,
            32,
            "%docs%",
            32,
            "$current_url",
            32,
            "properties",
            1,
            2,
            17,
            3,
            2,
            4,
            2,
            3,
            4,
        ]


class TestCohortExprHelpers(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def test_build_behavioral_event_expr_supported_with_event_filters(self):
        behavioral = {
            "type": "behavioral",
            "key": "$pageview",
            "value": "performed_event",
            "event_type": "events",
            "event_filters": [{"type": "event", "key": "$browser", "operator": "is_set", "value": "is_set"}],
        }
        expr = build_behavioral_event_expr(behavioral, self.team)
        assert expr is not None
        bytecode = create_bytecode(expr).bytecode
        assert bytecode == [
            "_H",
            HOGQL_BYTECODE_VERSION,
            32,
            "$pageview",
            32,
            "event",
            1,
            1,
            11,
            31,
            32,
            "$browser",
            32,
            "properties",
            1,
            2,
            12,
            3,
            2,
        ]

    def test_build_behavioral_event_expr_unsupported_returns_none(self):
        behavioral = {
            "type": "behavioral",
            "key": "$pageview",
            "value": "performed_event_regularly",
            "event_type": "events",
        }
        expr = build_behavioral_event_expr(behavioral, self.team)
        # Unsupported behavioral filters return None
        assert expr is None

    def test_cohort_filters_to_expr_and_bytecode(self):
        filters = {
            "properties": {
                "type": "AND",
                "values": [
                    {
                        "type": "behavioral",
                        "key": "$pageview",
                        "value": "performed_event_multiple",
                        "event_type": "events",
                        "event_filters": [
                            {"type": "event", "key": "$browser", "operator": "is_set", "value": "is_set"}
                        ],
                    },
                    {"type": "person", "key": "email", "operator": "exact", "value": "test@example.com"},
                ],
            }
        }
        expr = cohort_filters_to_expr(filters, self.team)
        bytecode = create_bytecode(expr).bytecode
        assert bytecode == [
            "_H",
            HOGQL_BYTECODE_VERSION,
            32,
            "$pageview",
            32,
            "event",
            1,
            1,
            11,
            31,
            32,
            "$browser",
            32,
            "properties",
            1,
            2,
            12,
            3,
            2,
            32,
            "test@example.com",
            32,
            "email",
            32,
            "properties",
            32,
            "person",
            1,
            3,
            11,
            3,
            2,
        ]


class TestCohortInlining(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    def _make_person_property_cohort(self, properties: list[dict] | dict) -> Cohort:
        return Cohort.objects.create(
            team=self.team,
            name="Person property cohort",
            filters={"properties": properties},
            is_static=False,
        )

    def test_person_property_cohort_inlined_in_test_account_filters(self):
        cohort = self._make_person_property_cohort(
            {
                "type": "AND",
                "values": [
                    {"type": "person", "key": "email", "operator": "not_icontains", "value": "@test.com"},
                    {"type": "person", "key": "is_internal", "operator": "is_not", "value": "true"},
                ],
            }
        )
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": cohort.pk}]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result.get("bytecode") is not None, f"Expected bytecode but got error: {result.get('bytecode_error')}"
        assert "bytecode_error" not in result

    def test_person_property_cohort_with_negation(self):
        cohort = self._make_person_property_cohort(
            {
                "type": "AND",
                "values": [
                    {"type": "person", "key": "email", "operator": "icontains", "value": "@posthog.com"},
                ],
            }
        )
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": cohort.pk, "negation": True}]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result.get("bytecode") is not None, f"Expected bytecode but got error: {result.get('bytecode_error')}"

        # The negated cohort should produce a NOT(...) expression that compiles to bytecode
        hog_globals = {"person": {"properties": {"email": "test@other.com"}}}
        res = execute_bytecode(result["bytecode"], hog_globals)
        assert res.result is True

        # A person matching the cohort should be filtered out (NOT matches)
        hog_globals = {"person": {"properties": {"email": "ben@posthog.com"}}}
        res = execute_bytecode(result["bytecode"], hog_globals)
        assert res.result is False

    def test_person_property_cohort_mixed_with_regular_filters(self):
        cohort = self._make_person_property_cohort(
            {"type": "AND", "values": [{"type": "person", "key": "plan", "operator": "exact", "value": "enterprise"}]}
        )
        self.team.test_account_filters = [
            {"type": "cohort", "key": "id", "value": cohort.pk},
            {"type": "person", "key": "email", "operator": "not_icontains", "value": "@test.com"},
        ]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result.get("bytecode") is not None, f"Expected bytecode but got error: {result.get('bytecode_error')}"

        # Both filters should be applied: plan=enterprise AND email not containing @test.com
        hog_globals = {"person": {"properties": {"plan": "enterprise", "email": "user@real.com"}}}
        res = execute_bytecode(result["bytecode"], hog_globals)
        assert res.result is True

        hog_globals = {"person": {"properties": {"plan": "free", "email": "user@real.com"}}}
        res = execute_bytecode(result["bytecode"], hog_globals)
        assert res.result is False

    def test_behavioral_cohort_still_errors(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Behavioral cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "behavioral",
                            "key": "$pageview",
                            "value": "performed_event",
                            "event_type": "events",
                        }
                    ],
                }
            },
            is_static=False,
        )
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": cohort.pk}]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result["bytecode"] is None
        assert _normalize_error(result["bytecode_error"]) == (
            "Your internal/test user filters include cohorts that can't be used in real-time filters: "
            "cohort 'Behavioral cohort' (id=N) contains behavioral filters — "
            "only cohorts with exclusively person property filters can be used in real-time filters. "
            "Either switch to a cohort that only uses person properties, "
            "or replace the cohort with inline person property filters. "
            "Update your filters at: SETTINGS_URL#internal-user-filtering"
        )

    def test_nested_cohort_reference_still_errors(self):
        inner_cohort = Cohort.objects.create(
            team=self.team,
            name="Inner cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "exact", "value": "x@y.com"}],
                }
            },
            is_static=False,
        )
        outer_cohort = Cohort.objects.create(
            team=self.team,
            name="Outer cohort with nested ref",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "cohort", "key": "id", "value": inner_cohort.pk}],
                }
            },
            is_static=False,
        )
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": outer_cohort.pk}]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result["bytecode"] is None
        assert _normalize_error(result["bytecode_error"]) == (
            "Your internal/test user filters include cohorts that can't be used in real-time filters: "
            "cohort 'Outer cohort with nested ref' (id=N) contains cohort filters — "
            "only cohorts with exclusively person property filters can be used in real-time filters. "
            "Either switch to a cohort that only uses person properties, "
            "or replace the cohort with inline person property filters. "
            "Update your filters at: SETTINGS_URL#internal-user-filtering"
        )

    def test_nonexistent_cohort_falls_through_to_error(self):
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": 999999}]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result["bytecode"] is None
        assert _normalize_error(result["bytecode_error"]) == (
            "Your internal/test user filters include cohorts that can't be used in real-time filters: "
            "cohort id=N not found. "
            "Either switch to a cohort that only uses person properties, "
            "or replace the cohort with inline person property filters. "
            "Update your filters at: SETTINGS_URL#internal-user-filtering"
        )

    def test_multiple_person_property_cohorts_all_inlined(self):
        cohort1 = self._make_person_property_cohort(
            {"type": "AND", "values": [{"type": "person", "key": "role", "operator": "exact", "value": "admin"}]}
        )
        cohort2 = self._make_person_property_cohort(
            {"type": "AND", "values": [{"type": "person", "key": "org", "operator": "exact", "value": "internal"}]}
        )
        self.team.test_account_filters = [
            {"type": "cohort", "key": "id", "value": cohort1.pk},
            {"type": "cohort", "key": "id", "value": cohort2.pk},
        ]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result.get("bytecode") is not None, f"Expected bytecode but got error: {result.get('bytecode_error')}"

        hog_globals = {"person": {"properties": {"role": "admin", "org": "internal"}}}
        res = execute_bytecode(result["bytecode"], hog_globals)
        assert res.result is True

        hog_globals = {"person": {"properties": {"role": "user", "org": "internal"}}}
        res = execute_bytecode(result["bytecode"], hog_globals)
        assert res.result is False

    def test_exclude_test_and_internal_user_cohorts(self):
        test_users_cohort = Cohort.objects.create(
            team=self.team,
            name="Test users",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "$test_user", "operator": "exact", "value": "true"}],
                }
            },
            is_static=False,
        )
        internal_users_cohort = Cohort.objects.create(
            team=self.team,
            name="Internal users",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [{"type": "person", "key": "email", "operator": "icontains", "value": "@example.com"}],
                }
            },
            is_static=False,
        )
        self.team.test_account_filters = [
            {"type": "cohort", "key": "id", "value": test_users_cohort.pk, "negation": True},
            {"type": "cohort", "key": "id", "value": internal_users_cohort.pk, "negation": True},
        ]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result.get("bytecode") is not None, f"Expected bytecode but got error: {result.get('bytecode_error')}"
        assert "bytecode_error" not in result

        # Real external user — passes both filters
        hog_globals = {"person": {"properties": {"$test_user": "false", "email": "customer@gmail.com"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is True

        # Test user — filtered out by the test users cohort negation
        hog_globals = {"person": {"properties": {"$test_user": "true", "email": "customer@gmail.com"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is False

        # Internal user — filtered out by the internal users cohort negation
        hog_globals = {"person": {"properties": {"$test_user": "false", "email": "alice@example.com"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is False

        # Both test and internal — also filtered out
        hog_globals = {"person": {"properties": {"$test_user": "true", "email": "dev@example.com"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is False

    def test_cohort_with_or_structure_preserves_boolean_logic(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Internal domains",
            filters={
                "properties": {
                    "type": "OR",
                    "values": [
                        {"type": "person", "key": "email", "operator": "icontains", "value": "@example.com"},
                        {"type": "person", "key": "email", "operator": "icontains", "value": "@test.io"},
                    ],
                }
            },
            is_static=False,
        )
        # "not in cohort" = exclude anyone whose email matches either domain
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": cohort.pk, "negation": True}]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result.get("bytecode") is not None, f"Expected bytecode but got error: {result.get('bytecode_error')}"

        # External user — matches neither domain, passes filter
        hog_globals = {"person": {"properties": {"email": "customer@gmail.com"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is True

        # Matches first domain — filtered out
        hog_globals = {"person": {"properties": {"email": "alice@example.com"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is False

        # Matches second domain — also filtered out
        # (would incorrectly pass if OR was flattened to AND, since NOT(a AND b) != NOT(a OR b))
        hog_globals = {"person": {"properties": {"email": "bot@test.io"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is False

    def test_cohort_with_nested_and_or_structure(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Complex filter cohort",
            filters={
                "properties": {
                    "type": "AND",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {"type": "person", "key": "email", "operator": "icontains", "value": "@example.com"},
                                {"type": "person", "key": "email", "operator": "icontains", "value": "@test.io"},
                            ],
                        },
                        {"type": "person", "key": "role", "operator": "exact", "value": "engineer"},
                    ],
                }
            },
            is_static=False,
        )
        # Non-negated: include only people matching the cohort (internal engineers)
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": cohort.pk}]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result.get("bytecode") is not None, f"Expected bytecode but got error: {result.get('bytecode_error')}"

        # Matches both: internal domain AND engineer role
        hog_globals = {"person": {"properties": {"email": "alice@example.com", "role": "engineer"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is True

        # Matches domain but wrong role — fails the AND
        hog_globals = {"person": {"properties": {"email": "alice@example.com", "role": "designer"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is False

        # Right role but external domain — fails the OR
        hog_globals = {"person": {"properties": {"email": "alice@gmail.com", "role": "engineer"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is False

        # Second OR branch works: test.io domain + engineer
        hog_globals = {"person": {"properties": {"email": "bot@test.io", "role": "engineer"}}}
        assert execute_bytecode(result["bytecode"], hog_globals).result is True

    def test_empty_cohort_properties_falls_through(self):
        cohort = Cohort.objects.create(
            team=self.team,
            name="Empty cohort",
            filters={"properties": {}},
            is_static=False,
        )
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": cohort.pk}]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        # Empty properties caught by _try_inline_cohort_filter, raises CohortInlineError
        assert result["bytecode"] is None
        assert _normalize_error(result["bytecode_error"]) == (
            "Your internal/test user filters include cohorts that can't be used in real-time filters: "
            "cohort 'Empty cohort' (id=N) has no properties defined. "
            "Either switch to a cohort that only uses person properties, "
            "or replace the cohort with inline person property filters. "
            "Update your filters at: SETTINGS_URL#internal-user-filtering"
        )

import re
import json

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, QueryMatchingTest

from parameterized import parameterized

from posthog.hogql.compiler.bytecode import create_bytecode

from posthog.cdp.filters import (
    build_behavioral_event_expr,
    cohort_filters_to_expr,
    compile_filters_bytecode,
    hog_function_filters_to_expr,
)

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.operation import HOGQL_BYTECODE_VERSION


def _normalize_error(error: str) -> str:
    """Replace dynamic IDs and URLs in error messages with stable placeholders."""
    error = re.sub(r"id=\d+", "id=N", error)
    error = re.sub(r"https?://[^/]+/project/\d+/settings/project-customization", "SETTINGS_URL", error)
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

    @parameterized.expand(
        [
            (
                "trigger_filter_matches_row",
                {
                    "source": "data-warehouse-view",
                    "properties": [
                        {"key": "organization", "value": "acme", "operator": "exact", "type": "data_warehouse"}
                    ],
                },
                {"organization": "acme", "$source_table": "accounts"},
                True,
            ),
            (
                "trigger_filter_rejects_row",
                {
                    "source": "data-warehouse-view",
                    "properties": [
                        {"key": "organization", "value": "acme", "operator": "exact", "type": "data_warehouse"}
                    ],
                },
                {"organization": "globex", "$source_table": "accounts"},
                False,
            ),
            (
                "destination_table_filter_matches_row",
                {
                    "source": "data-warehouse-table",
                    "data_warehouse": [
                        {
                            "table_name": "postgres.accounts",
                            "properties": [
                                {"key": "organization", "value": "acme", "operator": "exact", "type": "data_warehouse"}
                            ],
                        }
                    ],
                },
                {"organization": "acme", "$source_table": "postgres.accounts"},
                True,
            ),
            (
                "destination_unfiltered_table_still_matches",
                {
                    "source": "data-warehouse-table",
                    "data_warehouse": [
                        {
                            "table_name": "postgres.accounts",
                            "properties": [
                                {"key": "organization", "value": "acme", "operator": "exact", "type": "data_warehouse"}
                            ],
                        },
                        {"table_name": "postgres.orders"},
                    ],
                },
                {"organization": "globex", "$source_table": "postgres.orders"},
                True,
            ),
            (
                "destination_unfiltered_table_does_not_bypass_filtered_table",
                {
                    "source": "data-warehouse-table",
                    "data_warehouse": [
                        {
                            "table_name": "postgres.accounts",
                            "properties": [
                                {"key": "organization", "value": "acme", "operator": "exact", "type": "data_warehouse"}
                            ],
                        },
                        {"table_name": "postgres.orders"},
                    ],
                },
                {"organization": "globex", "$source_table": "postgres.accounts"},
                False,
            ),
        ]
    )
    def test_warehouse_row_filters_match_row_columns(self, _name: str, filters: dict, row: dict, expected: bool):
        bytecode = self.filters_to_bytecode(filters=filters)
        assert execute_bytecode(bytecode, {"properties": row}).result is expected

    @parameterized.expand(
        [
            # The column hint lists bare names, so that is what people type into the SQL leaf.
            ("bare_column", {"type": "hogql", "key": "organization = 'acme'"}),
            # What an input template reads the row as.
            ("record_alias", {"type": "hogql", "key": "record.organization = 'acme'"}),
            # Already where the row is; must not become properties.properties.
            ("qualified_column", {"type": "hogql", "key": "properties.organization = 'acme'"}),
            # A lambda parameter is a local, not a column.
            ("lambda_local", {"type": "hogql", "key": "arrayExists(x -> x = 'acme', [organization])"}),
            # A lambda parameter named like the column shadows it inside the lambda only.
            (
                "lambda_shadows_column",
                {
                    "type": "hogql",
                    "key": "arrayExists(organization -> organization = 'acme', ['acme']) and organization = 'acme'",
                },
            ),
            # The same for the record alias.
            (
                "lambda_shadows_record",
                {
                    "type": "hogql",
                    "key": "arrayExists(record -> record = 'acme', ['acme']) and record.organization = 'acme'",
                },
            ),
        ]
    )
    def test_warehouse_sql_filters_read_columns_from_the_row(self, _name: str, prop: dict):
        for filters in (
            {"source": "data-warehouse-view", "properties": [prop]},
            {"source": "data-warehouse-table", "data_warehouse": [{"table_name": "accounts", "properties": [prop]}]},
        ):
            response = compile_filters_bytecode(filters=filters, team=self.team)
            assert "bytecode_error" not in response, response
            row = {"$source_table": "accounts"}
            assert (
                execute_bytecode(response["bytecode"], {"properties": {**row, "organization": "acme"}}).result is True
            )
            assert (
                execute_bytecode(response["bytecode"], {"properties": {**row, "organization": "globex"}}).result
                is False
            )

    def test_warehouse_sql_filter_keeps_a_block_local_over_the_column(self):
        # The `let` inside the lambda is a local named like the column; only the outer read is the column.
        response = compile_filters_bytecode(
            filters={
                "source": "data-warehouse-view",
                "properties": [
                    {
                        "type": "hogql",
                        "key": "arrayExists(x -> { let organization := 'acme'; return organization = 'acme' }, [1]) and organization = 'globex'",
                    }
                ],
            },
            team=self.team,
        )
        assert "bytecode_error" not in response, response
        assert execute_bytecode(response["bytecode"], {"properties": {"organization": "globex"}}).result is True

    def test_warehouse_filters_leave_the_team_test_account_filters_under_the_guard(self):
        # The rewrite is for the row the destination filters on. The team's filters are written
        # against events, so an unknown root there is still the team's mistake to fix.
        self.team.test_account_filters = [{"type": "hogql", "key": "$virt_is_bot = false"}]
        self.team.save()
        response = compile_filters_bytecode(
            filters={
                "source": "data-warehouse-view",
                "filter_test_accounts": True,
                "properties": [{"type": "hogql", "key": "organization = 'acme'"}],
            },
            team=self.team,
        )
        assert response["bytecode"] is None
        assert "internal/test user filters read $virt_is_bot" in response["bytecode_error"]
        assert "organization" not in response["bytecode_error"]

    def test_warehouse_sql_filter_reads_the_column_until_a_let_shadows_it(self):
        # `picked` reads the column, the `let` after it does not reach back.
        response = compile_filters_bytecode(
            filters={
                "source": "data-warehouse-view",
                "properties": [
                    {
                        "type": "hogql",
                        "key": "arrayExists(x -> { let picked := organization; let organization := 'other'; return picked = 'acme' }, [1])",
                    }
                ],
            },
            team=self.team,
        )
        assert "bytecode_error" not in response, response
        assert execute_bytecode(response["bytecode"], {"properties": {"organization": "acme"}}).result is True
        assert execute_bytecode(response["bytecode"], {"properties": {"organization": "other"}}).result is False

    def test_warehouse_sql_filter_keeps_a_recursive_lambda_local(self):
        # The lambda calls its own name, which must stay the local and not become the column.
        response = compile_filters_bytecode(
            filters={
                "source": "data-warehouse-view",
                "properties": [
                    {
                        "type": "hogql",
                        "key": "arrayExists(x -> { let organization := (n -> if(n = 'acme', true, organization('acme'))); return organization(x) }, ['zzz'])",
                    }
                ],
            },
            team=self.team,
        )
        assert "bytecode_error" not in response, response
        assert execute_bytecode(response["bytecode"], {"properties": {"organization": "other"}}).result is True

    def test_event_filters_still_reject_a_bare_unknown_column(self):
        # Only a warehouse row lives under properties; an event filter naming an unknown root is a typo.
        response = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "organization = 'acme'"}]}, team=self.team
        )
        assert "organization" in response["bytecode_error"]

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

    def test_filters_raise_on_a_global_the_runtime_does_not_have(self):
        # $virt_is_bot exists in HogQL query context but not in the globals the filter path
        # builds, so it compiles clean and then raises on every event the destination is offered.
        response = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "$virt_is_bot"}]},
            team=self.team,
        )
        assert "$virt_is_bot" in response["bytecode_error"]
        assert response["bytecode"] is None

    def test_filters_allow_a_global_the_runtime_does_have(self):
        response = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "person.properties.email is not null"}]},
            team=self.team,
        )
        assert "bytecode_error" not in response

    def test_filters_allow_what_the_other_consumers_compile(self):
        # Error tracking alerts and AI observability evaluations compile through this function too,
        # and error tracking turns any bytecode_error into a refused save. Their surfaces reduce to
        # roots the runtime provides, and this keeps that true.
        alert = compile_filters_bytecode(
            filters={
                "events": [
                    {
                        "id": "$exception",
                        "type": "events",
                        "properties": [{"key": "$exception_type", "value": "TypeError", "type": "event"}],
                    }
                ]
            },
            team=self.team,
        )
        assert "bytecode_error" not in alert

        evaluation = compile_filters_bytecode(
            filters={
                "properties": [{"key": "email", "value": "@example.com", "operator": "icontains", "type": "person"}]
            },
            team=self.team,
        )
        assert "bytecode_error" not in evaluation

    def test_filters_reject_a_global_only_some_callers_supply(self):
        # cohort_ids is built only by hogflow_conditional_branch, and only when the condition
        # references cohorts. Nothing this function compiles is ever evaluated with it present.
        response = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "has(cohort_ids, 1)"}]},
            team=self.team,
        )
        assert "cohort_ids" in response["bytecode_error"]

    def test_filters_allow_a_named_stl_callback(self):
        # The VM resolves a bare standard-library name through GET_GLOBAL and returns the callable,
        # so this filter runs. Only the async one cannot, because the filter path allows no async steps.
        ok = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "arrayMap(lower, ['A'])[1] = 'a'"}]},
            team=self.team,
        )
        assert "bytecode_error" not in ok

        rejected = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "arrayMap(sleep, [1])[1] = 1"}]},
            team=self.team,
        )
        assert "sleep" in rejected["bytecode_error"]

        # A bytecode standard-library name resolves to a closure the VM then refuses to call, so a
        # filter passing one as a callback throws on every event.
        not_invocable = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "arrayMap(sortableSemver, ['1.2.3'])[1] != []"}]},
            team=self.team,
        )
        assert "sortableSemver" in not_invocable["bytecode_error"]

        # A direct call compiles to a different instruction, which does run the same name.
        called_directly = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "sortableSemver('1.2.3')[1] = 1"}]},
            team=self.team,
        )
        assert "bytecode_error" not in called_directly

    def test_filters_reject_a_function_the_runtime_does_not_have(self):
        # max2 exists in the Python standard library and not in the Node VM. A data global such as
        # event is not callable either, because the VM resolves a direct call against its function
        # tables and never against the globals it was given.
        for key in ("max2(1, 2) > 1", "sleep(1) = 1", "event() = 'x'", "properties() = 'x'"):
            response = compile_filters_bytecode(filters={"properties": [{"type": "hogql", "key": key}]}, team=self.team)
            assert response.get("bytecode_error"), key
            assert key.split("(")[0] in response["bytecode_error"]

    def test_filters_reject_a_call_with_the_wrong_number_of_arguments(self):
        # Valid HogQL for a query, where dateAdd takes two arguments, and a run-time error in the VM,
        # where it takes three.
        for key, expected in (
            ("lower() = 'a'", "`lower` takes exactly 1 arguments, got 0"),
            ("inCohort(1)", "`inCohort` takes exactly 2 arguments, got 1"),
            ("dateAdd(toIntervalDay(1), timestamp) > now()", "`dateAdd` takes exactly 3 arguments, got 2"),
        ):
            response = compile_filters_bytecode(filters={"properties": [{"type": "hogql", "key": key}]}, team=self.team)
            assert expected in (response.get("bytecode_error") or ""), key

    def test_filters_reject_what_the_compiler_lowers_before_the_generic_check(self):
        for key, expected in (
            ("if(true, true)", "`if` takes exactly 3 arguments, got 2"),
            ("if(true, true, false, $virt_is_bot)", "`if` takes exactly 3 arguments, got 4"),
            ("sql(event) = 1", "`sql` is not implemented"),
            ("print(person.properties.email) = ''", "`print` is not implemented"),
            (
                "person.properties.email.startsWith('a')",
                "`person.properties.email.startsWith` is a value, not a function",
            ),
            ("(event)()", "`event` is a value, not a function"),
            ("multiIf(true, true, false, true)", "`multiIf` takes an odd number of arguments, got 4"),
        ):
            response = compile_filters_bytecode(filters={"properties": [{"type": "hogql", "key": key}]}, team=self.team)
            assert expected in (response.get("bytecode_error") or ""), key

        # The shape with a value to fall back to still compiles.
        odd = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "multiIf(true, true, false, true, false)"}]},
            team=self.team,
        )
        assert "bytecode_error" not in odd

        # A lambda parameter is a variable, and a variable that holds a function can be called.
        allowed = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "arrayMap(f -> f(1), [x -> x])[1] = 1"}]}, team=self.team
        )
        assert "bytecode_error" not in allowed

    def test_filters_name_the_team_settings_when_test_account_filters_cannot_run(self):
        self.team.test_account_filters = [{"type": "hogql", "key": "$virt_is_bot = false"}]
        self.team.save()

        result = compile_filters_bytecode({"filter_test_accounts": True}, self.team)
        assert result["bytecode"] is None
        assert _normalize_error(result["bytecode_error"]) == (
            "Your internal/test user filters read $virt_is_bot, which real-time filters cannot read. "
            "Check the spelling, or use a field or function that real-time filters support. "
            "Update your filters at: SETTINGS_URL#internal-user-filtering"
        )

        # A bad field in the destination on top of the project's names both sources, so a person
        # knows there are two places to fix.
        own = compile_filters_bytecode(
            {"filter_test_accounts": True, "properties": [{"type": "hogql", "key": "$virt_traffic_type = 'y'"}]},
            self.team,
        )
        assert _normalize_error(own["bytecode_error"]) == (
            "Your internal/test user filters read $virt_is_bot, which real-time filters cannot read. "
            "Check the spelling, or use a field or function that real-time filters support. "
            "This destination's own filters also read $virt_traffic_type. "
            "Update your filters at: SETTINGS_URL#internal-user-filtering"
        )

        # Both sources reading the same field must still name both, or the next save fails the same way.
        shared = compile_filters_bytecode(
            {"filter_test_accounts": True, "properties": [{"type": "hogql", "key": "$virt_is_bot = true"}]},
            self.team,
        )
        assert _normalize_error(shared["bytecode_error"]) == (
            "Your internal/test user filters read $virt_is_bot, which real-time filters cannot read. "
            "Check the spelling, or use a field or function that real-time filters support. "
            "This destination's own filters also read $virt_is_bot. "
            "Update your filters at: SETTINGS_URL#internal-user-filtering"
        )

    def test_filters_allow_group_globals(self):
        response = compile_filters_bytecode(
            filters={
                "properties": [{"type": "hogql", "key": "group_0.properties.name = 'a' and $group_1 is not null"}]
            },
            team=self.team,
        )
        assert "bytecode_error" not in response

    def test_filters_allow_a_lambda_parameter(self):
        # The parameter is a local, not a global. Reading the chain off the AST would reject this.
        response = compile_filters_bytecode(
            filters={"properties": [{"type": "hogql", "key": "arrayExists(x -> x = 'a', elements_chain_texts)"}]},
            team=self.team,
        )
        assert "bytecode_error" not in response

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

    def test_multi_value_exact_filter_matches_numeric_property(self):
        # Survey ratings and other numeric event properties arrive as numbers, while a multi-value
        # "exact" filter stores its values as strings. Membership must still match (it compiles to a
        # type-coercing equality chain, not a strict IN).
        filters = {
            "properties": [
                {
                    "key": "$survey_response_1",
                    "value": ["1", "2", "3", "4", "5", "6"],
                    "operator": "exact",
                    "type": "event",
                }
            ]
        }
        bytecode = compile_filters_bytecode(filters, self.team)["bytecode"]
        assert execute_bytecode(bytecode, {"properties": {"$survey_response_1": 6}}).result is True
        assert execute_bytecode(bytecode, {"properties": {"$survey_response_1": 7}}).result is False

    @parameterized.expand(
        [
            (True, True),
            ("true", True),
            (1, True),
            (False, False),
            ("false", False),
            (0, False),
        ]
    )
    def test_multi_value_exact_filter_matches_mcp_error_encodings(
        self, property_value: bool | str | int, expected: bool
    ) -> None:
        filters = {
            "events": [
                {
                    "id": "$mcp_tool_call",
                    "type": "events",
                    "properties": [
                        {
                            "key": "$mcp_is_error",
                            "value": ["true", True, 1],
                            "operator": "exact",
                            "type": "event",
                        }
                    ],
                }
            ]
        }
        bytecode = compile_filters_bytecode(filters, self.team)["bytecode"]

        assert (
            execute_bytecode(
                bytecode,
                {"event": "$mcp_tool_call", "properties": {"$mcp_is_error": property_value}},
            ).result
            is expected
        )

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

    @parameterized.expand(
        [
            # `detail` is a nested object on `$activity_log_entry_created`, so a `detail.name` filter
            # must resolve to `properties.detail.name` rather than a flat `properties["detail.name"]` key.
            (
                "activity_log_nested_detail_matches",
                {
                    "events": [{"id": "$activity_log_entry_created", "type": "events", "order": 0}],
                    "properties": [{"key": "detail.name", "value": "cheese", "operator": "icontains", "type": "event"}],
                },
                {"event": "$activity_log_entry_created", "properties": {"detail": {"name": "cheese wheel"}}},
                True,
            ),
            (
                "activity_log_nested_detail_does_not_match",
                {
                    "events": [{"id": "$activity_log_entry_created", "type": "events", "order": 0}],
                    "properties": [{"key": "detail.name", "value": "cheese", "operator": "icontains", "type": "event"}],
                },
                {"event": "$activity_log_entry_created", "properties": {"detail": {"name": "bananas"}}},
                False,
            ),
            # Outside internal events a dotted key stays a single flat property lookup, so existing
            # destinations keep matching properties whose names literally contain a dot.
            (
                "regular_event_dotted_key_stays_flat",
                {
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "properties": [{"key": "foo.bar", "value": "baz", "operator": "exact", "type": "event"}],
                },
                {"event": "$pageview", "properties": {"foo.bar": "baz"}},
                True,
            ),
            (
                "regular_event_dotted_key_not_treated_as_nested",
                {
                    "events": [{"id": "$pageview", "type": "events", "order": 0}],
                    "properties": [{"key": "foo.bar", "value": "baz", "operator": "exact", "type": "event"}],
                },
                {"event": "$pageview", "properties": {"foo": {"bar": "baz"}}},
                False,
            ),
            # A global property filter applies to every event branch, so when an internal event is
            # mixed with an analytics event the dotted key must stay flat — resolving it would break
            # the `$pageview` branch that reads `sdk.version` as a literal flat property.
            (
                "mixed_events_global_dotted_key_stays_flat",
                {
                    "events": [
                        {"id": "$activity_log_entry_created", "type": "events", "order": 0},
                        {"id": "$pageview", "type": "events", "order": 1},
                    ],
                    "properties": [{"key": "sdk.version", "value": "1.2", "operator": "exact", "type": "event"}],
                },
                {"event": "$pageview", "properties": {"sdk.version": "1.2"}},
                True,
            ),
        ]
    )
    def test_dotted_property_key_resolution(self, _name: str, filters: dict, hog_globals: dict, expected: bool):
        bytecode = self.filters_to_bytecode(filters=filters)
        assert execute_bytecode(bytecode, hog_globals).result is expected


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
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": cohort.pk, "operator": "not_in"}]
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
            {"type": "cohort", "key": "id", "value": test_users_cohort.pk, "operator": "not_in"},
            {"type": "cohort", "key": "id", "value": internal_users_cohort.pk, "operator": "not_in"},
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
        self.team.test_account_filters = [{"type": "cohort", "key": "id", "value": cohort.pk, "operator": "not_in"}]
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

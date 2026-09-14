import pytest

from parameterized import parameterized

from products.data_catalog.backend.facade.contracts import HogQLMetricDefinition
from products.data_quality.backend.facade.enums import CheckType, SubjectType
from products.data_quality.backend.logic.compiler import compile_check
from products.data_quality.backend.logic.contracts import Evaluation, SubjectRef
from products.data_quality.backend.logic.errors import CheckConfigError, SubjectUnresolvableError
from products.data_quality.backend.logic.registry import UnknownCheckTypeError, all_specs, get_spec, list_check_types
from products.data_quality.backend.logic.serialization import compute_fingerprint, from_config_entry, to_config_entry
from products.data_quality.backend.logic.spec import CheckTypeSpec, NoConfig
from products.data_quality.backend.logic.types.custom_sql import CustomSqlConfig, CustomSqlSpec

ORDERS = SubjectRef(SubjectType.VIEW, "1cd4a1ef-0000-0000-0000-000000000001", "orders", "orders", exists=True)
CUSTOMERS = SubjectRef(SubjectType.TABLE, "1cd4a1ef-0000-0000-0000-000000000002", "customers", "customers", True)

RELATIONSHIPS_CONFIG = {
    "to_subject_type": "table",
    "to_subject_uuid": "1cd4a1ef-0000-0000-0000-000000000002",
    "to_column": "id",
}


def _normalized(check_type, column_name, config) -> dict:
    """What the fingerprint hashes: config put through its type's model first."""
    return get_spec(check_type).validate(config, column_name).model_dump(mode="json")


def _fingerprint_for(config: dict) -> str:
    return compute_fingerprint(
        subject_type=SubjectType.VIEW,
        subject_uuid=ORDERS.subject_uuid,
        check_type=CheckType.NOT_NULL,
        column_name="customer_id",
        config=config,
    )


def _compile(check_type, column_name, config, related=None):
    return compile_check(
        check_type=check_type,
        subject=ORDERS,
        column_name=column_name,
        config=config,
        related_subject=related,
    )


class TestCheckCompiler:
    @pytest.mark.parametrize("subject_type", [SubjectType.METRIC, SubjectType.TABLE, SubjectType.VIEW])
    @pytest.mark.parametrize(
        ("query", "references", "has_cte"),
        [
            (
                "SELECT * FROM {metric} UNION ALL "
                "SELECT * FROM (WITH orders AS (SELECT 123 AS total) SELECT * FROM orders)",
                ["orders"],
                True,
            ),
            (
                "WITH metric_output AS (SELECT * FROM {metric}) "
                "SELECT * FROM metric_output UNION ALL SELECT * FROM metric_output",
                ["orders"],
                True,
            ),
            (
                "WITH metric_output AS (SELECT * FROM {metric}), orders AS (SELECT 123 AS total) "
                "SELECT * FROM metric_output JOIN orders ON 1 = 1",
                ["orders"],
                True,
            ),
            (
                "WITH orders AS (SELECT * FROM {metric}) SELECT * FROM orders",
                ["orders"],
                True,
            ),
            (
                "SELECT * FROM {metric} JOIN (SELECT 1 AS total) AS other ON total IN (SELECT total FROM customers)",
                ["customers", "orders"],
                False,
            ),
            (
                "SELECT * FROM {metric} UNION ALL SELECT * FROM customers",
                ["customers", "orders"],
                False,
            ),
        ],
    )
    def test_custom_sql_references_respect_cte_scope(
        self, subject_type: SubjectType, query: str, references: list[str], has_cte: bool
    ) -> None:
        subject = SubjectRef(
            subject_type,
            "1cd4a1ef-0000-0000-0000-000000000003",
            "orders",
            "orders",
            exists=True,
            metric_definition=HogQLMetricDefinition(query="SELECT * FROM orders", values={}),
        )
        config = CustomSqlConfig(
            query=query if subject_type == SubjectType.METRIC else query.replace("{metric}", "(SELECT * FROM orders)")
        )

        if subject_type == SubjectType.METRIC and has_cte:
            with pytest.raises(CheckConfigError, match="cannot use CTEs"):
                CustomSqlSpec().referenced_table_names(config, subject)
            return
        assert sorted(CustomSqlSpec().referenced_table_names(config, subject)) == references

    @parameterized.expand(
        [
            (
                "hogqlx_relation",
                SubjectType.TABLE,
                "SELECT * FROM <HogQLQuery query='SELECT * FROM customers' />",
                "SELECT * FROM orders",
            ),
            (
                "hogqlx_join",
                SubjectType.VIEW,
                "SELECT * FROM orders JOIN <HogQLQuery query='SELECT * FROM customers' /> ON 1 = 1",
                "SELECT * FROM orders",
            ),
            (
                "hogqlx_cte",
                SubjectType.VIEW,
                "WITH failures AS (SELECT * FROM <HogQLQuery query='SELECT * FROM customers' />) "
                "SELECT * FROM failures",
                "SELECT * FROM orders",
            ),
            (
                "hogqlx_metric_definition",
                SubjectType.METRIC,
                "SELECT * FROM {metric}",
                "SELECT * FROM <HogQLQuery query='SELECT * FROM customers' />",
            ),
            (
                "hogqlx_metric_check",
                SubjectType.METRIC,
                "SELECT * FROM {metric} JOIN <HogQLQuery query='SELECT * FROM customers' /> ON 1 = 1",
                "SELECT * FROM orders",
            ),
            (
                "table_function",
                SubjectType.TABLE,
                "SELECT * FROM numbers(10)",
                "SELECT * FROM orders",
            ),
        ]
    )
    def test_custom_sql_rejects_unenumerable_table_expressions(
        self, _name: str, subject_type: SubjectType, query: str, metric_query: str
    ) -> None:
        subject = SubjectRef(
            subject_type,
            "1cd4a1ef-0000-0000-0000-000000000003",
            "orders",
            "orders",
            exists=True,
            metric_definition=HogQLMetricDefinition(query=metric_query, values={}),
        )
        spec = CustomSqlSpec()
        config = CustomSqlConfig(query=query)

        with pytest.raises(CheckConfigError, match="table expression"):
            spec.referenced_table_names(config, subject)
        with pytest.raises(CheckConfigError, match="table expression"):
            compile_check(check_type=CheckType.CUSTOM_SQL, subject=subject, column_name="", config={"query": query})

    def test_custom_sql_is_the_only_metric_check_type(self) -> None:
        """Catches registry filtering custom SQL out of the metric check catalog."""
        assert {entry.check_type for entry in list_check_types("metric")} == {CheckType.CUSTOM_SQL}
        for kind in (SubjectType.TABLE, SubjectType.VIEW):
            assert len(list_check_types(kind)) == 7
            assert {entry.check_type for entry in list_check_types(kind)} == set(CheckType)
        with pytest.raises(UnknownCheckTypeError, match="metric_value"):
            _compile("metric_value", "", {"min": 1})

    def test_compiles_metric_custom_sql_through_the_row_query_path(self) -> None:
        """Catches the compiler rejecting metrics before custom SQL can bind their definition."""
        metric = SubjectRef(
            SubjectType.METRIC,
            "1cd4a1ef-0000-0000-0000-000000000003",
            "signups",
            "",
            exists=True,
            metric_definition=HogQLMetricDefinition(
                query="SELECT count() AS signups FROM events WHERE event = {event_name}",
                values={"event_name": "signup"},
            ),
        )

        compiled = compile_check(
            check_type=CheckType.CUSTOM_SQL,
            subject=metric,
            column_name="",
            config={"query": "SELECT * FROM {metric} WHERE signups < 100"},
        )

        assert compiled.printed_query == (
            "SELECT count() AS failure_count, count() AS observed_value "
            "FROM (SELECT * FROM (SELECT count() AS signups FROM events WHERE equals(event, 'signup')) "
            "WHERE less(signups, 100))"
        )

    def test_metric_custom_sql_hides_invalid_check_parser_details_during_compilation(self) -> None:
        """Catches Pydantic parsing a metric check before the binder can provide its stable error."""
        metric = SubjectRef(
            SubjectType.METRIC,
            "1cd4a1ef-0000-0000-0000-000000000003",
            "signups",
            "",
            exists=True,
            metric_definition=HogQLMetricDefinition(query="SELECT count() AS signups FROM events", values={}),
        )

        with pytest.raises(CheckConfigError, match="^Could not parse the metric custom_sql query\\.$"):
            compile_check(
                check_type=CheckType.CUSTOM_SQL,
                subject=metric,
                column_name="",
                config={"query": "SELECT * FORM {metric}"},
            )

    def test_metric_custom_sql_hides_invalid_check_parser_details_during_subject_validation(self) -> None:
        """Catches authoring validation leaking parser details before binding a metric check."""
        metric = SubjectRef(
            SubjectType.METRIC,
            "1cd4a1ef-0000-0000-0000-000000000003",
            "signups",
            "",
            exists=True,
            metric_definition=HogQLMetricDefinition(query="SELECT count() AS signups FROM events", values={}),
        )
        spec = get_spec(CheckType.CUSTOM_SQL)
        config = spec.validate({"query": "SELECT * FORM {metric}"}, "")

        with pytest.raises(CheckConfigError, match="^Could not parse the metric custom_sql query\\.$"):
            spec.referenced_table_names(config, metric)

    def test_table_custom_sql_keeps_its_existing_invalid_query_error(self) -> None:
        """Catches deferring metric parsing from changing table and view custom-SQL validation."""
        with pytest.raises(CheckConfigError):
            _compile(CheckType.CUSTOM_SQL, "", {"query": "SELECT * FORM orders"})

    @parameterized.expand(
        [
            (
                CheckType.NOT_NULL,
                "customer_id",
                {},
                None,
                "SELECT count() AS failure_count, count() AS observed_value "
                "FROM (SELECT 1 FROM orders WHERE isNull(customer_id))",
            ),
            (
                CheckType.UNIQUE,
                "id",
                {},
                None,
                "SELECT count() AS failure_count, count() AS observed_value "
                "FROM (SELECT id FROM orders WHERE isNotNull(id) GROUP BY id HAVING greater(count(), 1))",
            ),
            (
                CheckType.ACCEPTED_VALUES,
                "status",
                {"values": ["paid", "refunded"]},
                None,
                "SELECT count() AS failure_count, count() AS observed_value FROM (SELECT 1 FROM orders "
                "WHERE and(isNotNull(status), notIn(status, ['paid', 'refunded'])))",
            ),
            (
                CheckType.RELATIONSHIPS,
                "customer_id",
                RELATIONSHIPS_CONFIG,
                CUSTOMERS,
                "SELECT count() AS failure_count, count() AS observed_value FROM (SELECT 1 FROM orders "
                "WHERE and(isNotNull(customer_id), notIn(customer_id, (SELECT id FROM customers))))",
            ),
            (
                CheckType.ROW_COUNT,
                "",
                {"min": 1},
                None,
                "SELECT count() AS observed_value FROM (SELECT 1 FROM orders)",
            ),
            (
                CheckType.FRESHNESS,
                "created_at",
                {"max_age_minutes": 60},
                None,
                "SELECT countIf(or(isNull(staleness_seconds), greater(staleness_seconds, 3600))) AS failure_count, "
                "max(staleness_seconds) AS observed_value "
                "FROM (SELECT dateDiff('second', max(created_at), now()) AS staleness_seconds FROM orders)",
            ),
            (
                CheckType.CUSTOM_SQL,
                "",
                {"query": "select 1 from orders where total < 0"},
                None,
                "SELECT count() AS failure_count, count() AS observed_value "
                "FROM (SELECT 1 FROM orders WHERE less(total, 0))",
            ),
            (
                CheckType.CUSTOM_SQL,
                "",
                {"query": "select id from orders where total < 0 union all select id from orders where total > 100"},
                None,
                "SELECT count() AS failure_count, count() AS observed_value "
                "FROM (SELECT id FROM orders WHERE less(total, 0) "
                "UNION ALL SELECT id FROM orders WHERE greater(total, 100))",
            ),
        ]
    )
    def test_compiles_to_a_count_only_query(self, check_type, column_name, config, related, expected) -> None:
        assert _compile(check_type, column_name, config, related).printed_query == expected

    @parameterized.expand(
        [
            ("not_null", CheckType.NOT_NULL, "customer_id", {}, None, "SELECT * FROM orders WHERE isNull(customer_id)"),
            (
                "accepted_values",
                CheckType.ACCEPTED_VALUES,
                "status",
                {"values": ["paid"]},
                None,
                "SELECT * FROM orders WHERE and(isNotNull(status), notIn(status, ['paid']))",
            ),
            (
                "row_count",
                CheckType.ROW_COUNT,
                "",
                {"min": 1},
                None,
                "SELECT count() AS row_count FROM orders",
            ),
        ]
    )
    def test_the_stored_query_shows_the_offending_data(
        self, _name, check_type, column_name, config, related, expected
    ) -> None:
        # Failing rows are never persisted, so re-running this query is the only way a human can see
        # what broke -- a constant projection would answer with a column of 1s.
        assert _compile(check_type, column_name, config, related).printed_failing_rows_query == expected

    def test_freshness_fails_when_the_column_has_no_values_at_all(self) -> None:
        # An empty table or dead pipeline yields a null staleness; comparing null to the threshold
        # would silently pass, which is the exact case freshness is meant to catch.
        compiled = _compile(CheckType.FRESHNESS, "created_at", {"max_age_minutes": 60})

        assert "isNull(staleness_seconds)" in compiled.printed_query

    def test_row_count_is_the_only_type_not_using_zero_rows_pass(self) -> None:
        assert _compile(CheckType.ROW_COUNT, "", {"min": 1}).evaluation is Evaluation.BOUNDS
        assert _compile(CheckType.NOT_NULL, "id", {}).evaluation is Evaluation.ZERO_ROWS_PASS

    @parameterized.expand(
        [
            ("backtick", "we`ird", "col", "`we``ird`"),
            ("injection", "orders", 'foo"; DROP TABLE--', '`foo"; DROP TABLE--`'),
            ("unicode", "orders", "コラム", "`コラム`"),
        ]
    )
    def test_hostile_identifiers_are_escaped(self, _name, table, column_name, expected_fragment) -> None:
        subject = SubjectRef(SubjectType.VIEW, ORDERS.subject_uuid, table, table, exists=True)
        compiled = compile_check(check_type=CheckType.NOT_NULL, subject=subject, column_name=column_name, config={})
        assert expected_fragment in compiled.printed_query

    @parameterized.expand(
        [
            ("empty_accepted_values", CheckType.ACCEPTED_VALUES, "status", {"values": []}),
            ("unknown_config_key", CheckType.NOT_NULL, "id", {"tolerance": 5}),
            ("missing_column", CheckType.NOT_NULL, "", {}),
            ("row_count_without_bounds", CheckType.ROW_COUNT, "", {}),
            ("row_count_inverted_bounds", CheckType.ROW_COUNT, "", {"min": 10, "max": 1}),
            ("row_count_negative_min", CheckType.ROW_COUNT, "", {"min": -5}),
            ("row_count_negative_max", CheckType.ROW_COUNT, "", {"max": -1}),
            ("row_count_fractional_bound", CheckType.ROW_COUNT, "", {"min": 1.5}),
            (
                "relationships_to_metric",
                CheckType.RELATIONSHIPS,
                "customer_id",
                {**RELATIONSHIPS_CONFIG, "to_subject_type": "metric"},
            ),
            ("custom_sql_not_a_select", CheckType.CUSTOM_SQL, "", {"query": "drop table orders"}),
            (
                "custom_sql_with_placeholder",
                CheckType.CUSTOM_SQL,
                "",
                {"query": "select 1 from orders where {filters}"},
            ),
            ("freshness_without_threshold", CheckType.FRESHNESS, "created_at", {}),
        ]
    )
    def test_invalid_config_is_rejected(self, _name, check_type, column_name, config) -> None:
        with pytest.raises(CheckConfigError):
            _compile(check_type, column_name, config)

    def test_relationships_to_an_unresolvable_subject_is_rejected(self) -> None:
        missing = SubjectRef(SubjectType.TABLE, CUSTOMERS.subject_uuid, "", "", exists=False)
        with pytest.raises(SubjectUnresolvableError):
            _compile(CheckType.RELATIONSHIPS, "customer_id", RELATIONSHIPS_CONFIG, missing)

    def test_compiling_against_a_gone_subject_is_rejected(self) -> None:
        gone = SubjectRef(SubjectType.VIEW, ORDERS.subject_uuid, "", "", exists=False)
        with pytest.raises(SubjectUnresolvableError):
            compile_check(check_type=CheckType.NOT_NULL, subject=gone, column_name="id", config={})

    def test_unknown_check_type_names_the_supported_types(self) -> None:
        with pytest.raises(UnknownCheckTypeError, match="not_null"):
            _compile("anomaly", "id", {})

    def test_every_check_type_has_a_spec(self) -> None:
        assert {spec.type_name for spec in all_specs()} == set(CheckType)

    def test_every_spec_publishes_a_generated_json_schema(self) -> None:
        # The schema is what the check_types endpoint and the MCP tool docs hand to agents, and it
        # is derived from the config model rather than written by hand, so it cannot drift from
        # what parse_config actually accepts.
        for spec in all_specs():
            assert isinstance(spec, CheckTypeSpec)
            schema = spec.json_schema
            assert schema["type"] == "object"
            assert schema["additionalProperties"] is False, f"{spec.type_name} silently ignores unknown keys"

    def test_a_spec_missing_part_of_the_contract_cannot_be_instantiated(self) -> None:
        # An ABC rather than a Protocol so this fails here, not on the first agent to use it.
        class Incomplete(CheckTypeSpec):
            type_name = CheckType.NOT_NULL
            config_model = NoConfig
            requires_column = False
            description = "no build method"

        with pytest.raises(TypeError, match="build"):
            Incomplete()  # type: ignore[abstract]


class TestCheckSerialization:
    @parameterized.expand(
        [
            ("integer", {"min": 1}, {"min": 1, "max": None}),
            ("integral_float_min", {"min": 1.0}, {"min": 1, "max": None}),
            ("integral_float_max", {"max": 2.0}, {"min": None, "max": 2}),
            ("integral_float_bounds", {"min": 1.0, "max": 2.0}, {"min": 1, "max": 2}),
        ]
    )
    def test_row_count_bounds_preserve_existing_fingerprint(self, _name: str, config: dict, expected: dict) -> None:
        normalized = _normalized(CheckType.ROW_COUNT, "", config)
        assert _fingerprint_for(normalized) == _fingerprint_for(expected)

    @parameterized.expand([(check_type,) for check_type in CheckType])
    def test_config_entry_round_trips(self, check_type) -> None:
        check = {
            "name": "orders_check",
            "description": "why it exists",
            "subject_type": SubjectType.VIEW,
            "subject_uuid": ORDERS.subject_uuid,
            "column_name": "customer_id",
            "check_type": check_type,
            "config": {"values": ["a"], "max_age_minutes": 60},
            "severity": "warn",
            "enabled": False,
            "tags": ["finance"],
        }
        entry = to_config_entry(check)
        assert to_config_entry(from_config_entry(entry)) == entry

    def test_fingerprint_changes_when_the_assertion_changes(self) -> None:
        def fingerprint(column_name: str, values: list[str]) -> str:
            return compute_fingerprint(
                subject_type=SubjectType.VIEW,
                subject_uuid=ORDERS.subject_uuid,
                check_type=CheckType.ACCEPTED_VALUES,
                column_name=column_name,
                config=_normalized(CheckType.ACCEPTED_VALUES, column_name, {"values": values}),
            )

        assert fingerprint("status", ["paid", "refunded"]) != fingerprint("status", ["paid"])
        assert fingerprint("status", ["paid", "refunded"]) != fingerprint("total", ["paid", "refunded"])

    def test_accepted_values_fingerprint_ignores_order_and_duplicates(self) -> None:
        # accepted_values is a set: reordering or repeating a value must not create a twin check that
        # slips past the fingerprint uniqueness constraint.
        canonical = _normalized(CheckType.ACCEPTED_VALUES, "status", {"values": ["paid", "refunded"]})
        shuffled = _normalized(CheckType.ACCEPTED_VALUES, "status", {"values": ["refunded", "paid", "paid"]})

        assert canonical == shuffled
        assert _fingerprint_for(canonical) == _fingerprint_for(shuffled)

    @parameterized.expand(
        [
            ("int_column", "Int64", ["1", "2"], [1.0, 2.0]),
            ("int_column_accepts_a_whole_float", "Int64", [2.0], [2.0]),
            ("nullable_int_column", "Nullable(Int64)", ["1"], [1.0]),
            ("low_cardinality_int_column", "LowCardinality(Int64)", ["1"], [1.0]),
            ("low_cardinality_nullable_int_column", "LowCardinality(Nullable(Int64))", ["1"], [1.0]),
            ("float_column", "Float64", ["1.5"], [1.5]),
            ("bool_column", "Bool", ["true", "FALSE"], [False, True]),
            ("string_column", "String", ["1", "paid"], ["1", "paid"]),
            ("low_cardinality_string_column", "LowCardinality(String)", ["1", "paid"], ["1", "paid"]),
            ("string_column_reads_a_number_as_text", "String", [200], ["200"]),
            ("string_column_reads_a_float_as_text", "String", [1.5], ["1.5"]),
            ("string_column_reads_a_bool_as_text", "String", [True], ["true"]),
            ("low_cardinality_string_reads_a_number_as_text", "LowCardinality(String)", [200], ["200"]),
            ("unknown_column_type", None, ["1"], ["1"]),
        ]
    )
    def test_accepted_values_are_read_as_the_column_reads_them(self, _name, column_type, given, expected) -> None:
        # The editor's value control only produces strings, so without this a numeric column is
        # compared against strings and "1" fingerprints differently from the 1 an agent sends.
        spec = get_spec(CheckType.ACCEPTED_VALUES)
        parsed = spec.validate({"values": given}, "status")

        coerced = spec.coerce_to_column(parsed, column_type)

        assert coerced.model_dump(mode="json")["values"] == expected

    @parameterized.expand(
        [
            ("a word on a numeric column", "Int64", ["paid"]),
            ("a word on a boolean column", "Bool", ["paid"]),
            ("a boolean on a numeric column", "Int64", [True]),
            ("a fraction on an integer column", "Int64", [1.5]),
        ]
    )
    def test_an_accepted_value_the_column_cannot_hold_is_rejected(self, _name, column_type, given) -> None:
        # Better to say so at authoring time than to store a check that can never match a row.
        spec = get_spec(CheckType.ACCEPTED_VALUES)
        parsed = spec.validate({"values": given}, "status")

        with pytest.raises(CheckConfigError):
            spec.coerce_to_column(parsed, column_type)

    @parameterized.expand(
        [
            ("numeric_column", "Int64", "1", 1),
            ("text_column", "String", "200", 200),
        ]
    )
    def test_a_string_and_a_number_for_the_same_value_share_a_fingerprint(
        self, _name, column_type, ui_value, agent_value
    ) -> None:
        # The UI sends a string and an agent sends a bare scalar for the same check; they must upsert
        # onto one row rather than becoming twins, whether the column reads numbers or text.
        spec = get_spec(CheckType.ACCEPTED_VALUES)
        from_ui = spec.coerce_to_column(spec.validate({"values": [ui_value]}, "status"), column_type)
        from_agent = spec.coerce_to_column(spec.validate({"values": [agent_value]}, "status"), column_type)

        assert _fingerprint_for(from_ui.model_dump(mode="json")) == _fingerprint_for(from_agent.model_dump(mode="json"))

    def test_configs_that_differ_only_in_json_type_share_a_fingerprint(self) -> None:
        # Normalizing through the type's model first is what makes this hold: an agent sending
        # max_age_minutes as "60" must upsert the check it already created with 60, not add a twin.
        as_int = _normalized(CheckType.FRESHNESS, "created_at", {"max_age_minutes": 60})
        as_string = _normalized(CheckType.FRESHNESS, "created_at", {"max_age_minutes": "60"})

        assert as_int == as_string
        assert _fingerprint_for(as_int) == _fingerprint_for(as_string)

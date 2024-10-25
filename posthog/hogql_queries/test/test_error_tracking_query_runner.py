from unittest import TestCase
from freezegun import freeze_time

from posthog.hogql_queries.error_tracking_query_runner import ErrorTrackingQueryRunner, search_tokenizer
from posthog.schema import (
    ErrorTrackingQuery,
    DateRange,
    FilterLogicalOperator,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    PersonPropertyFilter,
    PropertyOperator,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    snapshot_clickhouse_queries,
    _create_person,
    _create_event,
    flush_persons_and_events,
)
from posthog.models import ErrorTrackingGroup
from datetime import datetime
from zoneinfo import ZoneInfo

SAMPLE_STACK_TRACE = [
    {
        "abs_path": "/code/posthog/clickhouse/client/execute.py",
        "context_line": "            result = client.execute(",
        "filename": "posthog/clickhouse/client/execute.py",
        "function": "sync_execute",
        "in_app": True,
        "lineno": 142,
        "module": "posthog.clickhouse.client.execute",
        "post_context": [
            "                prepared_sql,",
            "                params=prepared_args,",
            "                settings=settings,",
            "                with_column_types=with_column_types,",
            "                query_id=query_id,",
        ],
        "pre_context": [
            "            **core_settings,",
            '            "log_comment": json.dumps(tags, separators=(",", ":")),',
            "        }",
            "",
            "        try:",
        ],
    },
    {
        "abs_path": "/python-runtime/clickhouse_driver/client.py",
        "context_line": "                rv = self.process_ordinary_query(",
        "filename": "clickhouse_driver/client.py",
        "function": "execute",
        "lineno": 382,
        "module": "clickhouse_driver.client",
        "post_context": [
            "                    query, params=params, with_column_types=with_column_types,",
            "                    external_tables=external_tables,",
            "                    query_id=query_id, types_check=types_check,",
            "                    columnar=columnar",
            "                )",
        ],
        "pre_context": [
            "                    query, params, external_tables=external_tables,",
            "                    query_id=query_id, types_check=types_check,",
            "                    columnar=columnar",
            "                )",
            "            else:",
        ],
    },
    {
        "abs_path": "/python-runtime/clickhouse_driver/client.py",
        "context_line": "        return self.receive_result(with_column_types=with_column_types,",
        "filename": "clickhouse_driver/client.py",
        "function": "process_ordinary_query",
        "lineno": 580,
        "module": "clickhouse_driver.client",
        "post_context": [
            "                                   columnar=columnar)",
            "",
            "    def iter_process_ordinary_query(",
            "            self, query, params=None, with_column_types=False,",
            "            external_tables=None, query_id=None,",
        ],
        "pre_context": [
            "                query, params, self.connection.context",
            "            )",
            "        self.connection.send_query(query, query_id=query_id, params=params)",
            "        self.connection.send_external_tables(external_tables,",
            "                                             types_check=types_check)",
        ],
    },
    {
        "abs_path": "/python-runtime/clickhouse_driver/client.py",
        "context_line": "            return result.get_result()",
        "filename": "clickhouse_driver/client.py",
        "function": "receive_result",
        "lineno": 213,
        "module": "clickhouse_driver.client",
        "post_context": [
            "",
            "    def iter_receive_result(self, with_column_types=False):",
            "        gen = self.packet_generator()",
            "",
            "        result = self.iter_query_result_cls(",
        ],
        "pre_context": [
            "",
            "        else:",
            "            result = self.query_result_cls(",
            "                gen, with_column_types=with_column_types, columnar=columnar",
            "            )",
        ],
    },
    {
        "abs_path": "/python-runtime/clickhouse_driver/result.py",
        "context_line": "        for packet in self.packet_generator:",
        "filename": "clickhouse_driver/result.py",
        "function": "get_result",
        "lineno": 50,
        "module": "clickhouse_driver.result",
        "post_context": [
            "            self.store(packet)",
            "",
            "        data = self.data",
            "        if self.columnar:",
            "            data = [tuple(c) for c in self.data]",
        ],
        "pre_context": [
            "    def get_result(self):",
            '        """',
            "        :return: stored query result.",
            '        """',
            "",
        ],
    },
    {
        "abs_path": "/python-runtime/clickhouse_driver/client.py",
        "context_line": "                packet = self.receive_packet()",
        "filename": "clickhouse_driver/client.py",
        "function": "packet_generator",
        "lineno": 229,
        "module": "clickhouse_driver.client",
        "post_context": [
            "                if not packet:",
            "                    break",
            "",
            "                if packet is True:",
            "                    continue",
        ],
        "pre_context": [
            "                yield row",
            "",
            "    def packet_generator(self):",
            "        while True:",
            "            try:",
        ],
    },
    {
        "abs_path": "/python-runtime/clickhouse_driver/client.py",
        "context_line": "            raise packet.exception",
        "filename": "clickhouse_driver/client.py",
        "function": "receive_packet",
        "lineno": 246,
        "module": "clickhouse_driver.client",
        "post_context": [
            "",
            "        elif packet.type == ServerPacketTypes.PROGRESS:",
            "            self.last_query.store_progress(packet.progress)",
            "            return packet",
            "",
        ],
        "pre_context": [
            "",
            "    def receive_packet(self):",
            "        packet = self.connection.receive_packet()",
            "",
            "        if packet.type == ServerPacketTypes.EXCEPTION:",
        ],
    },
]


class TestErrorTrackingQueryRunner(ClickhouseTestMixin, APIBaseTest):
    distinct_id_one = "user_1"
    distinct_id_two = "user_2"

    def setUp(self):
        super().setUp()

        with freeze_time("2020-01-10 12:11:00"):
            _create_person(
                team=self.team,
                distinct_ids=[self.distinct_id_one],
                is_identified=True,
            )
            _create_person(
                team=self.team,
                properties={
                    "email": "email@posthog.com",
                    "name": "Test User",
                },
                distinct_ids=[self.distinct_id_two],
                is_identified=True,
            )

            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["SyntaxError"],
                    "$exception_list": [
                        {
                            "type": "SyntaxError",
                            "value": "this is the same error message",
                        }
                    ],
                },
            )
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={"$exception_fingerprint": ["TypeError"], "$exception_list": [{"type": "TypeError"}]},
            )
            _create_event(
                distinct_id=self.distinct_id_two,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["SyntaxError"],
                    "$exception_list": [{"type": "SyntaxError", "value": "this is the same error message"}],
                },
            )
            _create_event(
                distinct_id=self.distinct_id_two,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["custom_fingerprint"],
                    "$exception_list": [{"type": "SyntaxError", "value": "this is the same error message"}],
                },
            )

        flush_persons_and_events()

    def _calculate(self, runner: ErrorTrackingQueryRunner):
        return runner.calculate().model_dump()

    @snapshot_clickhouse_queries
    def test_column_names(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=None,
                dateRange=DateRange(),
                filterTestAccounts=True,
            ),
        )

        columns = self._calculate(runner)["columns"]
        self.assertEqual(
            columns,
            [
                "occurrences",
                "sessions",
                "users",
                "last_seen",
                "first_seen",
                "description",
                "exception_type",
                "fingerprint",
            ],
        )

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=["SyntaxError"],
                dateRange=DateRange(),
                filterTestAccounts=True,
            ),
        )

        columns = self._calculate(runner)["columns"]
        self.assertEqual(
            columns,
            [
                "occurrences",
                "sessions",
                "users",
                "last_seen",
                "first_seen",
                "description",
                "exception_type",
            ],
        )

    @snapshot_clickhouse_queries
    def test_search_query(self):
        with freeze_time("2022-01-10 12:11:00"):
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["DatabaseNotFoundX"],
                    "$exception_list": [{"type": "DatabaseNotFoundX", "value": "this is the same error message"}],
                },
            )
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["DatabaseNotFoundY"],
                    "$exception_list": [{"type": "DatabaseNotFoundY", "value": "this is the same error message"}],
                },
            )
            _create_event(
                distinct_id=self.distinct_id_two,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["xyz"],
                    "$exception_list": [{"type": "xyz", "value": "this is the same error message"}],
                },
            )
            flush_persons_and_events()

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=None,
                dateRange=DateRange(date_from="2022-01-10", date_to="2022-01-11"),
                filterTestAccounts=True,
                searchQuery="databasenot",
            ),
        )

        results = sorted(self._calculate(runner)["results"], key=lambda x: x["fingerprint"])

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["fingerprint"], ["DatabaseNotFoundX"])
        self.assertEqual(results[0]["occurrences"], 1)
        self.assertEqual(results[0]["sessions"], 1)
        self.assertEqual(results[0]["users"], 1)

        self.assertEqual(results[1]["fingerprint"], ["DatabaseNotFoundY"])
        self.assertEqual(results[1]["occurrences"], 1)
        self.assertEqual(results[1]["sessions"], 1)
        self.assertEqual(results[1]["users"], 1)

    def test_empty_search_query(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=None,
                dateRange=DateRange(),
                filterTestAccounts=False,
                searchQuery="probs not found",
            ),
        )

        results = self._calculate(runner)["results"]

        self.assertEqual(len(results), 0)

    @snapshot_clickhouse_queries
    def test_search_query_with_multiple_search_items(self):
        with freeze_time("2022-01-10 12:11:00"):
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["DatabaseNotFoundX"],
                    "$exception_list": [
                        {
                            "type": "DatabaseNotFoundX",
                            "value": "this is the same error message",
                            "stack_trace": {"frames": SAMPLE_STACK_TRACE},
                        }
                    ],
                },
            )

            _create_event(
                distinct_id=self.distinct_id_two,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["DatabaseNotFoundY"],
                    "$exception_list": [
                        {
                            "type": "DatabaseNotFoundY",
                            "value": "this is the same error message",
                            "stack_trace": {"frames": SAMPLE_STACK_TRACE},
                        }
                    ],
                },
            )
            flush_persons_and_events()

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=None,
                dateRange=DateRange(),
                filterTestAccounts=True,
                searchQuery="databasenotfoundX clickhouse/client/execute.py",
            ),
        )

        results = self._calculate(runner)["results"]

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["fingerprint"], ["DatabaseNotFoundX"])
        self.assertEqual(results[0]["occurrences"], 1)
        self.assertEqual(results[0]["sessions"], 1)
        self.assertEqual(results[0]["users"], 1)

    @snapshot_clickhouse_queries
    def test_search_query_with_null_characters(self):
        fingerprint_with_null_bytes = [
            "SyntaxError",
            "Cannot use 'in' operator to search for 'wireframes' in \x1f\x8b\x08\x00\x94\x0cýf\x00\x03ì½é\x96\"¹\x920ø*Lö¹SY\x1dA\x00Î\x9e÷Ô\x9df\r\x88\x00Ø",
        ]
        exception_type_with_null_bytes = "SyntaxError\x00"
        exception_message_with_null_bytes = "this is the same error message\x00"
        exception_stack_trace_with_null_bytes = {
            "frames": [
                {
                    "filename": "file.py\x00",
                    "lineno": 1,
                    "colno": 1,
                    "function": "function\x00",
                    "extra": "Cannot use 'in' operator to search for 'wireframes' in \x1f\x8b\x08\x00\x94\x0cýf\x00\x03ì½é\x96\"¹\x920ø*Lö¹SY\x1dA\x00Î\x9e÷Ô\x9df\r\x88\x00Ø",
                }
            ]
        }
        with freeze_time("2021-01-10 12:11:00"):
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": fingerprint_with_null_bytes,
                    "$exception_list": [
                        {
                            "type": exception_type_with_null_bytes,
                            "value": exception_message_with_null_bytes,
                            "stack_trace": exception_stack_trace_with_null_bytes,
                        }
                    ],
                },
            )
        flush_persons_and_events()

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                searchQuery="wireframe",
                dateRange=DateRange(date_from="2021-01-10", date_to="2021-01-11"),
            ),
        )

        results = self._calculate(runner)["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["fingerprint"], fingerprint_with_null_bytes)
        self.assertEqual(results[0]["occurrences"], 1)

        # TODO: Searching for null characters doesn't work, probs because of how clickhouse handles this. Should it work???
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                searchQuery="f\x00\x03ì½é",
                dateRange=DateRange(date_from="2021-01-10", date_to="2021-01-11"),
            ),
        )
        results = self._calculate(runner)["results"]
        self.assertEqual(len(results), 0)

    @snapshot_clickhouse_queries
    def test_fingerprints(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=["SyntaxError"],
                dateRange=DateRange(),
            ),
        )

        results = self._calculate(runner)["results"]
        # returns a single group with multiple errors
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["fingerprint"], ["SyntaxError"])
        self.assertEqual(results[0]["occurrences"], 2)

    @snapshot_clickhouse_queries
    def test_fingerprints_with_null_characters(self):
        fingerprint_with_null_bytes = [
            "SyntaxError",
            "Cannot use 'in' operator to search for 'wireframes' in \x1f\x8b\x08\x00\x94\x0cýf\x00\x03ì½é\x96\"\x00Ø",
        ]
        exception_type_with_null_bytes = "SyntaxError\x00"
        exception_message_with_null_bytes = "this is the same error message\x00"
        exception_stack_trace_with_null_bytes = {
            "frames": [{"filename": "file.py\x00", "lineno": 1, "colno": 1, "function": "function\x00"}]
        }
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$exception",
                team=self.team,
                properties={
                    "$exception_fingerprint": fingerprint_with_null_bytes,
                    "$exception_list": [
                        {
                            "type": exception_type_with_null_bytes,
                            "value": exception_message_with_null_bytes,
                            "stack_trace": exception_stack_trace_with_null_bytes,
                        }
                    ],
                },
            )
        flush_persons_and_events()

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                fingerprint=fingerprint_with_null_bytes,
                dateRange=DateRange(),
            ),
        )

        results = self._calculate(runner)["results"]
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["fingerprint"], fingerprint_with_null_bytes)
        self.assertEqual(results[0]["occurrences"], 1)

    def test_only_returns_exception_events(self):
        with freeze_time("2020-01-10 12:11:00"):
            _create_event(
                distinct_id=self.distinct_id_one,
                event="$pageview",
                team=self.team,
                properties={
                    "$exception_fingerprint": ["SyntaxError"],
                },
            )
        flush_persons_and_events()

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
            ),
        )

        results = self._calculate(runner)["results"]
        self.assertEqual(len(results), 3)

    @snapshot_clickhouse_queries
    def test_hogql_filters(self):
        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
                filterGroup=PropertyGroupFilter(
                    type=FilterLogicalOperator.AND_,
                    values=[
                        PropertyGroupFilterValue(
                            type=FilterLogicalOperator.OR_,
                            values=[
                                PersonPropertyFilter(
                                    key="email", value="email@posthog.com", operator=PropertyOperator.EXACT
                                ),
                            ],
                        )
                    ],
                ),
            ),
        )

        results = self._calculate(runner)["results"]
        # two errors exist for person with distinct_id_two
        self.assertEqual(len(results), 2)

    def test_merges_and_defaults_groups(self):
        ErrorTrackingGroup.objects.create(
            team=self.team,
            fingerprint=["SyntaxError"],
            merged_fingerprints=[["custom_fingerprint"]],
            assignee=self.user,
        )

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery", fingerprint=None, dateRange=DateRange(), order="occurrences"
            ),
        )

        results = self._calculate(runner)["results"]
        self.assertEqual(
            results,
            [
                {
                    "assignee": self.user.id,
                    "description": "this is the same error message",
                    "exception_type": "SyntaxError",
                    "fingerprint": ["SyntaxError"],
                    "first_seen": datetime(2020, 1, 10, 12, 11, tzinfo=ZoneInfo("UTC")),
                    "last_seen": datetime(2020, 1, 10, 12, 11, tzinfo=ZoneInfo("UTC")),
                    "merged_fingerprints": [["custom_fingerprint"]],
                    # count is (2 x SyntaxError) + (1 x custom_fingerprint)
                    "occurrences": 3,
                    "sessions": 1,
                    "users": 2,
                    "volume": None,
                    "status": ErrorTrackingGroup.Status.ACTIVE,
                },
                {
                    "assignee": None,
                    "description": None,
                    "exception_type": "TypeError",
                    "fingerprint": ["TypeError"],
                    "first_seen": datetime(2020, 1, 10, 12, 11, tzinfo=ZoneInfo("UTC")),
                    "last_seen": datetime(2020, 1, 10, 12, 11, tzinfo=ZoneInfo("UTC")),
                    "merged_fingerprints": [],
                    "occurrences": 1,
                    "sessions": 1,
                    "users": 1,
                    "volume": None,
                    "status": ErrorTrackingGroup.Status.ACTIVE,
                },
            ],
        )

    @snapshot_clickhouse_queries
    def test_assignee_groups(self):
        ErrorTrackingGroup.objects.create(
            team=self.team,
            fingerprint=["SyntaxError"],
            assignee=self.user,
        )
        ErrorTrackingGroup.objects.create(
            team=self.team,
            fingerprint=["custom_fingerprint"],
            assignee=self.user,
        )
        ErrorTrackingGroup.objects.create(
            team=self.team,
            fingerprint=["TypeError"],
        )

        runner = ErrorTrackingQueryRunner(
            team=self.team,
            query=ErrorTrackingQuery(
                kind="ErrorTrackingQuery",
                dateRange=DateRange(),
                assignee=self.user.pk,
            ),
        )

        results = self._calculate(runner)["results"]

        self.assertEqual(sorted([x["fingerprint"] for x in results]), [["SyntaxError"], ["custom_fingerprint"]])


class TestSearchTokenizer(TestCase):
    test_cases = [
        (
            "This is a \"quoted string\" and this is 'another one' with some words",
            ["This", "is", "a", "quoted string", "and", "this", "is", "another one", "with", "some", "words"],
        ),
        (
            "Empty quotes: \"\" and '' should be preserved",
            ["Empty", "quotes:", "", "and", "", "should", "be", "preserved"],
        ),
        ("Nested \"quotes 'are' tricky\" to handle", ["Nested", "quotes 'are' tricky", "to", "handle"]),
        (
            "Unmatched quotes: \"open quote and 'partial quote",
            ["Unmatched", "quotes:", "open", "quote", "and", "partial", "quote"],
        ),
        ("Multiple     spaces      between words", ["Multiple", "spaces", "between", "words"]),
        (
            "Special characters: @#$% should be treated as words",
            ["Special", "characters:", "@#$%", "should", "be", "treated", "as", "words"],
        ),
        (
            "Single quotes at \"start\" and 'end' of string",
            ["Single", "quotes", "at", "start", "and", "end", "of", "string"],
        ),
        ('"Entire string is quoted"', ["Entire string is quoted"]),
        ('Escaped quotes: "He said "Hello" to me"', ["Escaped", "quotes:", "He said ", "Hello", "to", "me"]),
    ]

    def test_tokenizer(self):
        for case, output in self.test_cases:
            with self.subTest(case=case):
                tokens = search_tokenizer(case)
                self.assertEqual(tokens, output)

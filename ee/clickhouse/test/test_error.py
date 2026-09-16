import pytest
from unittest.mock import MagicMock

from clickhouse_driver.errors import NetworkError, ServerException, SocketTimeoutError

from posthog.clickhouse.client import sync_execute
from posthog.errors import (
    CH_TRANSIENT_ERRORS,
    DELIMITED_ROW_SPLIT_MISMATCH_MESSAGE,
    QueryErrorCategory,
    classify_query_error,
    clickhouse_error_type,
    wrap_clickhouse_query_error,
)
from posthog.exceptions import ClickHouseClusterMemoryLimitExceeded, ClickHouseQueryMemoryLimitExceeded


@pytest.mark.parametrize(
    "error,expected_type,expected_message,expected_code,expected_ch_error",
    [
        (AttributeError("Foobar"), "AttributeError", "Foobar", None, "AttributeError"),
        (
            ServerException(
                "Estimated query execution time (34.5 seconds) is too long. Aborting query",
                code=160,
            ),
            "ClickHouseEstimatedQueryExecutionTimeTooLong",
            "Estimated query execution time (34.5 seconds) is too long. Try reducing its scope by changing the time range.",
            None,
            "CHQueryErrorTooSlow",
        ),
        (
            ServerException("Syntax error", code=62),
            "CHQueryErrorSyntaxError",
            "Code: 62.\nSyntax error",
            62,
            "CHQueryErrorSyntaxError",
        ),
        (
            ServerException("Syntax error", code=9999),
            "CHQueryErrorUnknownException",
            "Code: 9999.\nSyntax error",
            9999,
            "CHQueryErrorUnknownException",
        ),
        (
            ServerException(
                "Memory limit (for query) exceeded: would use 42.00 GiB (attempt to allocate chunk of 16757643 bytes), maximum: 42.00 GiB.",
                code=241,
            ),
            "ClickHouseQueryMemoryLimitExceeded",
            "This query ran out of memory before it could finish, usually because it's scanning too much data. Try a shorter date range or narrower filters, or see our docs for more ways to speed it up: https://posthog.com/docs/product-analytics/troubleshooting#how-do-i-speed-up-my-insights-and-queries",
            None,
            "CHQueryErrorMemoryLimitExceeded",
        ),
        (
            ServerException("Too many simultaneous queries. Maximum: 100.", code=202),
            "ClickHouseAtCapacity",
            "Queries are a little too busy right now. We're working to free up resources. Please try again later.",
            None,
            "CHQueryErrorTooManySimultaneousQueries",
        ),
        (
            ServerException(
                "Code: 439. DB::Exception: Cannot schedule a task: cannot allocate thread (threads=36, jobs=36). (CANNOT_SCHEDULE_TASK) (version 25.8.12.129 (official build))",
                code=439,
            ),
            "ClickHouseAtCapacity",
            "Queries are a little too busy right now. We're working to free up resources. Please try again later.",
            None,
            "CHQueryErrorCannotScheduleTask",
        ),
        (
            ServerException(
                "Code: 159. DB::Exception: Timeout exceeded: elapsed 60.046752587 seconds, maximum: 60. (TIMEOUT_EXCEEDED) (version 25.8.12.129 (official build))",
                code=159,
            ),
            "ClickHouseQueryTimeOut",
            "Query has hit the max execution time before completing. See our docs for how to improve your query performance. You may need to materialize.",
            None,
            "CHQueryErrorTimeoutExceeded",
        ),
        (
            ServerException(
                "Code: 499. DB::Exception: Failed to get object info: No response body.. HTTP response code: 404: while reading file.parquet",
                code=499,
            ),
            "CHQueryErrorS3Error",
            "Code: 499.\nS3 error occurred. (Code: 499. DB::Exception: Failed to get object info: No response body.. HTTP response code: 404: while reading file.parquet)",
            499,
            "CHQueryErrorS3Error",
        ),
        (
            ServerException(
                "Code: 499. DB::Exception: Unable to parse ExceptionName: InvalidRange Message: The requested range is not satisfiable: (in file/uri some-bucket/mongo/users.6.parquet): While executing ParquetV3BlockInputFormat: While executing ReadFromObjectStorage. Stack trace:\n\n0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x00000000141cccd0",
                code=499,
            ),
            "CHQueryErrorS3FileChangedDuringRead",
            "A file backing a data warehouse table changed while the query was reading it (some-bucket/mongo/users.6.parquet). "
            "Retry the query. If you manage these files yourself, avoid overwriting files in place: "
            "upload new files and delete old ones instead.",
            499,
            "CHQueryErrorS3Error",
        ),
        (
            ServerException(
                "Code: 117. DB::Exception: Not a Parquet file (wrong magic bytes at the end of file): (in file/uri some-bucket/mongo/users.52.parquet): While executing ParquetV3BlockInputFormat. Stack trace:\n\n0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x00000000141cccd0",
                code=117,
            ),
            "CHQueryErrorS3FileChangedDuringRead",
            "A file backing a data warehouse table changed while the query was reading it (some-bucket/mongo/users.52.parquet). "
            "Retry the query. If you manage these files yourself, avoid overwriting files in place: "
            "upload new files and delete old ones instead.",
            117,
            "CHQueryErrorIncorrectData",
        ),
        (
            ServerException(
                "DB::Exception: Cannot read all data. Bytes read: 5. Bytes expected: 100.",
                code=117,
            ),
            "CHQueryErrorIncorrectData",
            "Code: 117.\nDB::Exception: Cannot read all data. Bytes read: 5. Bytes expected: 100.",
            117,
            "CHQueryErrorIncorrectData",
        ),
        (
            ServerException(
                "Code: 467. DB::Exception: Cannot parse boolean value here: 'null', should be 'true' or 'false' controlled by setting bool_true_representation and bool_false_representation: while converting 'null' to Bool. Stack trace:\n\n0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x00000000141cccd0",
                code=467,
            ),
            "CHQueryErrorCannotParseBool",
            "Cannot parse boolean value here: 'null', should be 'true' or 'false' controlled by setting bool_true_representation and bool_false_representation: while converting 'null' to Bool.",
            467,
            "CHQueryErrorCannotParseBool",
        ),
        (
            ServerException(
                "Code: 376. DB::Exception: Cannot parse uuid 2026072018044213140: while converting '2026072018044213140' to UUID: while executing function equals. Stack trace:\n\n0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x00000000141cccd0",
                code=376,
            ),
            "CHQueryErrorCannotParseUuid",
            "Cannot parse uuid 2026072018044213140: while converting '2026072018044213140' to UUID: while executing function equals.",
            376,
            "CHQueryErrorCannotParseUuid",
        ),
        (
            ServerException(
                "Code: 43. DB::Exception: Illegal type String of argument of function toInt64.",
                code=43,
            ),
            "CHQueryErrorIllegalTypeOfArgument",
            "Illegal type String of argument of function toInt64.",
            43,
            "CHQueryErrorIllegalTypeOfArgument",
        ),
        (
            ServerException(
                "Code: 386. DB::Exception: There is no common type for types String, Int64.",
                code=386,
            ),
            "CHQueryErrorNoCommonType",
            "There is no common type for types String, Int64.",
            386,
            "CHQueryErrorNoCommonType",
        ),
        (
            ServerException(
                "Code: 215. DB::Exception: Column count is not an aggregate function.",
                code=215,
            ),
            "CHQueryErrorNotAnAggregate",
            "Column count is not an aggregate function.",
            215,
            "CHQueryErrorNotAnAggregate",
        ),
        (
            ServerException(
                "Code: 46. DB::Exception: Unknown function foobar.",
                code=46,
            ),
            "CHQueryErrorUnknownFunction",
            "Unknown function foobar.",
            46,
            "CHQueryErrorUnknownFunction",
        ),
        (
            ServerException(
                "Code: 53. DB::Exception: Type mismatch in IN or VALUES section.",
                code=53,
            ),
            "CHQueryErrorTypeMismatch",
            "Type mismatch in IN or VALUES section.",
            53,
            "CHQueryErrorTypeMismatch",
        ),
        (
            ServerException(
                "Code: 184. DB::Exception: Aggregate function sum(count()) is found inside another aggregate function.",
                code=184,
            ),
            "CHQueryErrorIllegalAggregation",
            "Aggregate function sum(count()) is found inside another aggregate function.",
            184,
            "CHQueryErrorIllegalAggregation",
        ),
        (
            ServerException(
                "Code: 60. DB::Exception: Unknown table expression identifier 'nonexistent'.",
                code=60,
            ),
            "CHQueryErrorUnknownTable",
            "Unknown table expression identifier 'nonexistent'.",
            60,
            "CHQueryErrorUnknownTable",
        ),
        (
            # A CSV row that the chosen quote setting mis-splits. The per-column dump repeats the
            # customer's own rows, so the wrapper replaces the whole message.
            ServerException(
                "Code: 27. DB::Exception: Cannot parse input: expected ',' before: "
                "'Ltd\",Bristol,2026-03-04\\n': (at row 12)\n: \nRow 12:\n"
                'Column 0,   name: account,   type: Nullable(String), parsed text: "Acme, Ltd"\n'
                'Column 1,   name: city,      type: Nullable(String), parsed text: "Bristol"\n'
                ": While executing ParallelParsingBlockInputFormat: While executing ReadFromObjectStorage. "
                "Stack trace:\n\n"
                "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
                code=27,
            ),
            "CHQueryErrorDelimitedRowSplitMismatch",
            DELIMITED_ROW_SPLIT_MISMATCH_MESSAGE,
            27,
            "CHQueryErrorCannotParseInputAssertionFailed",
        ),
        (
            # Same code, but a JSON file the reader rejects. The quote setting is not the fix, and
            # the message carries file content, so this one stays internal.
            ServerException(
                "DB::Exception: Cannot parse input: expected '{' before: "
                "'\"value\": 3}]': (while reading the value of key items): (at row 1)\n"
                ": (in file/uri example-bucket/exports/orders.jsonl): While executing "
                "ParallelParsingBlockInputFormat. Stack trace:\n\n"
                "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
                code=27,
            ),
            "CHQueryErrorCannotParseInputAssertionFailed",
            "Code: 27.\nDB::Exception: Cannot parse input: expected '{' before: "
            "'\"value\": 3}]': (while reading the value of key items): (at row 1)\n"
            ": (in file/uri example-bucket/exports/orders.jsonl): While executing "
            "ParallelParsingBlockInputFormat. Stack trace:\n\n"
            "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
            27,
            "CHQueryErrorCannotParseInputAssertionFailed",
        ),
        (
            # A JSON file that itself holds a whole column line of the dump. ClickHouse echoes the
            # text it stopped on, so only the row marker above the line tells a real dump from a
            # file that quotes one.
            ServerException(
                "DB::Exception: Cannot parse input: expected ',' before: "
                '\'{"notes": "...\n'
                "Column 0,   name: notes,   type: Nullable(String), parsed text: none}]': "
                "(while reading the value of key notes): (at row 1)\n"
                ": (in file/uri example-bucket/exports/notes.jsonl): While executing "
                "ParallelParsingBlockInputFormat. Stack trace:\n\n"
                "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
                code=27,
            ),
            "CHQueryErrorCannotParseInputAssertionFailed",
            "Code: 27.\nDB::Exception: Cannot parse input: expected ',' before: "
            '\'{"notes": "...\n'
            "Column 0,   name: notes,   type: Nullable(String), parsed text: none}]': "
            "(while reading the value of key notes): (at row 1)\n"
            ": (in file/uri example-bucket/exports/notes.jsonl): While executing "
            "ParallelParsingBlockInputFormat. Stack trace:\n\n"
            "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
            27,
            "CHQueryErrorCannotParseInputAssertionFailed",
        ),
        (
            # A CSV row that did split into the right number of columns, where one value doesn't
            # fit the column type. ClickHouse dumps the row above the failing one in full, so the
            # message carries parsed text as well. The quote setting is not the fix, and the
            # message names the column and the value, so this one stays internal.
            ServerException(
                "DB::Exception: Cannot parse input: expected ',' before: 'gold,2026-03-04\\n': "
                "(at row 9)\n: \nRow 8:\n"
                'Column 0,   name: amount,   type: Int64,  parsed text: "42"\n'
                'Column 1,   name: tier,     type: String, parsed text: "silver"\n'
                "\nRow 9:\n"
                'Column 0,   name: amount,   type: Int64,  ERROR: text "gold,2026-03-04<LINE FEED>" '
                "is not like Int64\n"
                ": (in file/uri example-bucket/exports/orders.csv): While executing "
                "ParallelParsingBlockInputFormat. Stack trace:\n\n"
                "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
                code=27,
            ),
            "CHQueryErrorCannotParseInputAssertionFailed",
            "Code: 27.\nDB::Exception: Cannot parse input: expected ',' before: 'gold,2026-03-04\\n': "
            "(at row 9)\n: \nRow 8:\n"
            'Column 0,   name: amount,   type: Int64,  parsed text: "42"\n'
            'Column 1,   name: tier,     type: String, parsed text: "silver"\n'
            "\nRow 9:\n"
            'Column 0,   name: amount,   type: Int64,  ERROR: text "gold,2026-03-04<LINE FEED>" '
            "is not like Int64\n"
            ": (in file/uri example-bucket/exports/orders.csv): While executing "
            "ParallelParsingBlockInputFormat. Stack trace:\n\n"
            "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
            27,
            "CHQueryErrorCannotParseInputAssertionFailed",
        ),
        (
            # The same wrong-value shape on a nullable column, which is what a file-backed table
            # usually infers. ClickHouse reads the value as empty and reports what is left over,
            # so the failing column names the type in its own wording. This stays internal too.
            ServerException(
                "DB::Exception: Cannot parse input: expected ',' before: 'gold,2026-03-04\\n': "
                "(at row 9)\n: \nRow 8:\n"
                'Column 0,   name: amount,   type: Nullable(Int64),  parsed text: "42"\n'
                'Column 1,   name: tier,     type: Nullable(String), parsed text: "silver"\n'
                "\nRow 9:\n"
                "Column 0,   name: amount,   type: Nullable(Int64),  parsed text: <EMPTY>\n"
                'ERROR: garbage after Nullable(Int64): "gold,2026-03-04<LINE FEED>"\n'
                ": (in file/uri example-bucket/exports/orders.csv): While executing "
                "ParallelParsingBlockInputFormat. Stack trace:\n\n"
                "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
                code=27,
            ),
            "CHQueryErrorCannotParseInputAssertionFailed",
            "Code: 27.\nDB::Exception: Cannot parse input: expected ',' before: 'gold,2026-03-04\\n': "
            "(at row 9)\n: \nRow 8:\n"
            'Column 0,   name: amount,   type: Nullable(Int64),  parsed text: "42"\n'
            'Column 1,   name: tier,     type: Nullable(String), parsed text: "silver"\n'
            "\nRow 9:\n"
            "Column 0,   name: amount,   type: Nullable(Int64),  parsed text: <EMPTY>\n"
            'ERROR: garbage after Nullable(Int64): "gold,2026-03-04<LINE FEED>"\n'
            ": (in file/uri example-bucket/exports/orders.csv): While executing "
            "ParallelParsingBlockInputFormat. Stack trace:\n\n"
            "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
            27,
            "CHQueryErrorCannotParseInputAssertionFailed",
        ),
        (
            # A mis-split row as ClickHouse really reports one: the dump ends with the failing
            # column's diagnostic, which names the delimiter it could not find. The quote advice
            # belongs to this shape, so narrowing the wrong-value shapes out must keep it.
            ServerException(
                "Code: 27. DB::Exception: Cannot parse input: expected ',' before: "
                "'Inc\",London,2026-03-05\\n': (at row 12)\n: \nRow 11:\n"
                'Column 0,   name: account,   type: Nullable(String), parsed text: "Acme, Ltd"\n'
                'Column 1,   name: city,      type: Nullable(String), parsed text: "Bristol"\n'
                "\nRow 12:\n"
                "Column 0,   name: account,   type: Nullable(String), parsed text: "
                '"<DOUBLE QUOTE>Widgets<DOUBLE QUOTE>"\n'
                'ERROR: There is no delimiter (,). "I" found instead.\n'
                ": (in file/uri example-bucket/exports/accounts.csv): While executing "
                "ParallelParsingBlockInputFormat. Stack trace:\n\n"
                "0. DB::Exception::Exception(DB::Exception::MessageMasked&&, int, bool) @ 0x0000000015979590",
                code=27,
            ),
            "CHQueryErrorDelimitedRowSplitMismatch",
            DELIMITED_ROW_SPLIT_MISMATCH_MESSAGE,
            27,
            "CHQueryErrorCannotParseInputAssertionFailed",
        ),
        (
            # Same code again, raised by a value that fails to convert inside a query. Nothing here
            # is about a file, and the message carries the value, so it stays internal too.
            ServerException(
                "DB::Exception: Cannot parse infinity: while converting 'gold' to Float64: "
                "while executing 'FUNCTION equals(accurateCastOrNull(__table1.mat_tier, 'Float64'_String) :: 2, "
                "'gold'_String :: 4) -> equals(...) Nullable(UInt8) : 3'.",
                code=27,
            ),
            "CHQueryErrorCannotParseInputAssertionFailed",
            "Code: 27.\nDB::Exception: Cannot parse infinity: while converting 'gold' to Float64: "
            "while executing 'FUNCTION equals(accurateCastOrNull(__table1.mat_tier, 'Float64'_String) :: 2, "
            "'gold'_String :: 4) -> equals(...) Nullable(UInt8) : 3'.",
            27,
            "CHQueryErrorCannotParseInputAssertionFailed",
        ),
    ],
)
def test_wrap_clickhouse_query_error(error, expected_type, expected_message, expected_code, expected_ch_error):
    label = clickhouse_error_type(error)
    new_error = wrap_clickhouse_query_error(error)
    assert type(new_error).__name__ == expected_type
    assert str(new_error) == expected_message
    assert getattr(new_error, "code", None) == expected_code
    assert label == expected_ch_error


# Marked for the database it queries: `django_db_setup` is what creates the ClickHouse test
# database, so without this the test only passes when some other test in the package happens to
# run first and create it, and fails wherever sharding isolates it.
@pytest.mark.django_db
def test_per_query_memory_limit_phrasing_matches_real_clickhouse():
    with pytest.raises(ClickHouseQueryMemoryLimitExceeded) as ctx:
        sync_execute(
            "SELECT groupArray(number) FROM numbers(10000000)",
            settings={"max_memory_usage": 1_000_000},
        )
    assert ctx.value.is_per_query_limit
    assert not isinstance(ctx.value, ClickHouseClusterMemoryLimitExceeded)


@pytest.mark.parametrize(
    "message,expected_per_query",
    [
        ("DB::Exception: Memory limit (for query) exceeded: would use 1.00 GiB, maximum: 900.00 MiB.", True),
        ("DB::Exception: Query memory limit exceeded: would use 1.00 GiB, maximum: 900.00 MiB.", True),
        (
            "DB::Exception: (total) memory limit exceeded: would use 270.76 GiB, maximum: 660.53 GiB. : While executing Remote.",
            False,
        ),
        ("DB::Exception: Memory limit (for user) exceeded: would use 1.00 GiB, maximum: 900.00 MiB.", False),
    ],
)
def test_memory_limit_wraps_by_which_ceiling_was_hit(message, expected_per_query):
    wrapped = wrap_clickhouse_query_error(ServerException(message, code=241))
    assert isinstance(wrapped, ClickHouseQueryMemoryLimitExceeded)
    assert wrapped.is_per_query_limit is expected_per_query

    # A ceiling the query did not set is cluster pressure: it lands on the class every retry path
    # keys off, and classifies as rate-limited capacity rather than a query-performance problem.
    is_cluster = isinstance(wrapped, ClickHouseClusterMemoryLimitExceeded)
    assert is_cluster is (not expected_per_query)
    if is_cluster:
        assert isinstance(wrapped, CH_TRANSIENT_ERRORS)
        assert classify_query_error(wrapped) == QueryErrorCategory.RATE_LIMITED


@pytest.mark.parametrize(
    "error",
    [
        SocketTimeoutError("(clickhouse.example.com:9440)"),
        NetworkError("Connection refused (clickhouse.example.com:9440)"),
    ],
)
def test_failing_to_open_a_clickhouse_connection_is_transient(error):
    assert isinstance(wrap_clickhouse_query_error(error), CH_TRANSIENT_ERRORS)


def test_a_driver_error_the_wrapper_passes_through_is_not_its_own_cause():
    error = SocketTimeoutError("(clickhouse.example.com:9440)")
    client = MagicMock()
    client.__enter__.return_value = client
    client.execute.side_effect = error

    with pytest.raises(SocketTimeoutError) as raised:
        sync_execute("SELECT 1", sync_client=client)

    assert raised.value is error
    assert raised.value.__cause__ is None


def test_a_mis_split_csv_row_is_the_customers_file_not_a_platform_failure():
    error = ServerException(
        "Code: 27. DB::Exception: Cannot parse input: expected ',' at end of stream: (at row 4)\n: \nRow 4:\n"
        'Column 0,   name: region,   type: Nullable(String), parsed text: "north, west"\n'
        ": While executing ParallelParsingBlockInputFormat. Stack trace:\n\n"
        "0. DB::Exception::Exception() @ 0x0000000015979590",
        code=27,
    )

    assert classify_query_error(wrap_clickhouse_query_error(error)) == QueryErrorCategory.USER_ERROR

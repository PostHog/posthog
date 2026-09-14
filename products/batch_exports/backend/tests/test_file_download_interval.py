import datetime as dt

import pytest
import time_machine

from products.batch_exports.backend.api.file_download import FileDownloadCountRowsRequestSerializer


@pytest.mark.parametrize(
    "hogql_query",
    [
        "SELECT {data_interval_start} AS bound",
        "SELECT {data_interval_end} AS bound",
        "SELECT {data_interval_start} AS start, {data_interval_end} AS end",
    ],
    ids=["start-placeholder", "end-placeholder", "both-placeholders"],
)
@pytest.mark.parametrize(
    "bounds",
    [
        {},
        {"data_interval_start": "2026-01-01T00:00:00Z"},
        {"data_interval_end": "2026-01-02T00:00:00Z"},
    ],
    ids=["no-bounds", "only-start", "only-end"],
)
def test_interval_placeholders_require_both_download_bounds(hogql_query: str, bounds: dict[str, str]) -> None:
    serializer = FileDownloadCountRowsRequestSerializer(data={"model": "hogql", "hogql_query": hogql_query, **bounds})

    assert not serializer.is_valid()
    assert "'data_interval_start' and 'data_interval_end' are required" in str(serializer.errors)


@pytest.mark.parametrize("with_placeholders", [False, True])
@pytest.mark.parametrize(
    "bounds,error",
    [
        ({}, None),
        ({"data_interval_start": "2026-01-01T00:00:00Z"}, "are required"),
        ({"data_interval_start": None, "data_interval_end": "2026-01-02T00:00:00Z"}, "may not be null"),
        ({"data_interval_start": "2026-01-01T00:00:00Z", "data_interval_end": None}, "may not be null"),
        (
            {"data_interval_start": "2026-01-01T00:00:00Z", "data_interval_end": "2026-01-08T00:00:00Z"},
            None,
        ),
        (
            {"data_interval_start": "2026-01-01T01:00:00+01:00", "data_interval_end": "2026-01-08T00:00:00Z"},
            None,
        ),
        (
            {"data_interval_start": "2026-01-01T00:00:00Z", "data_interval_end": "2026-01-08T00:00:00.000001Z"},
            "at most seven days",
        ),
        (
            {"data_interval_start": "2026-01-02T00:00:00Z", "data_interval_end": "2026-01-01T00:00:00Z"},
            "must occur after",
        ),
        (
            {"data_interval_start": "2026-01-01T00:00:00Z", "data_interval_end": "2026-01-01T00:00:00Z"},
            None,
        ),
        (
            {"data_interval_start": "2026-01-08T00:00:00Z", "data_interval_end": "2026-01-09T00:00:00Z"},
            "in the future",
        ),
    ],
    ids=[
        "no-bounds",
        "partial",
        "null-start",
        "null-end",
        "one-week",
        "timezone",
        "over-one-week",
        "reversed",
        "empty",
        "future",
    ],
)
@time_machine.travel("2026-01-08T00:00:00Z", tick=False)
def test_download_interval_validation(
    with_placeholders: bool, bounds: dict[str, str | None], error: str | None
) -> None:
    query = (
        "SELECT {data_interval_start} AS start, {data_interval_end} AS end"
        if with_placeholders
        else "SELECT 1 AS value"
    )
    if with_placeholders and not bounds:
        error = "are required"
    serializer = FileDownloadCountRowsRequestSerializer(data={"model": "hogql", "hogql_query": query, **bounds})

    if error is not None:
        assert not serializer.is_valid()
        assert error in str(serializer.errors)
    else:
        assert serializer.is_valid(), serializer.errors
        for name, value in bounds.items():
            assert value is not None
            assert serializer.validated_data[name] == dt.datetime.fromisoformat(value)


def test_placeholder_like_text_does_not_require_download_bounds() -> None:
    serializer = FileDownloadCountRowsRequestSerializer(
        data={"model": "hogql", "hogql_query": "SELECT '{data_interval_start}' AS value /* {data_interval_end} */"}
    )

    assert serializer.is_valid(), serializer.errors

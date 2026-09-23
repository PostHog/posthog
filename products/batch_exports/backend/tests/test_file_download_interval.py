import datetime as dt

import pytest
import time_machine

from products.batch_exports.backend.api.file_download import (
    FileDownloadBatchExportOnDemandSerializer,
    FileDownloadCountRowsRequestSerializer,
)


@pytest.mark.parametrize(
    "hogql_query,required_bounds",
    [
        ("SELECT {data_interval_start} AS bound", {"data_interval_start"}),
        ("SELECT {data_interval_end} AS bound", {"data_interval_end"}),
        (
            "SELECT {data_interval_start} AS start, {data_interval_end} AS end",
            {"data_interval_start", "data_interval_end"},
        ),
        ("SELECT 1 AS value", set()),
    ],
    ids=["start-placeholder", "end-placeholder", "both-placeholders", "no-placeholders"],
)
@pytest.mark.parametrize(
    "bounds",
    [
        {},
        {"data_interval_start": "2026-01-01T00:00:00Z"},
        {"data_interval_end": "2026-01-02T00:00:00Z"},
        {"data_interval_start": "2026-01-01T00:00:00Z", "data_interval_end": "2026-01-02T00:00:00Z"},
    ],
    ids=["no-bounds", "only-start", "only-end", "both-bounds"],
)
@time_machine.travel("2026-01-08T00:00:00Z", tick=False)
def test_interval_placeholders_require_only_referenced_download_bounds(
    hogql_query: str, required_bounds: set[str], bounds: dict[str, str]
) -> None:
    serializer = FileDownloadCountRowsRequestSerializer(data={"model": "hogql", "hogql_query": hogql_query, **bounds})

    missing = required_bounds - bounds.keys()
    if missing:
        assert not serializer.is_valid()
        assert set(serializer.errors) == missing
    else:
        assert serializer.is_valid(), serializer.errors


@pytest.mark.parametrize("with_placeholders", [False, True])
@pytest.mark.parametrize(
    "bounds,error",
    [
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
    serializer = FileDownloadCountRowsRequestSerializer(data={"model": "hogql", "hogql_query": query, **bounds})

    if error is not None:
        assert not serializer.is_valid()
        assert error in str(serializer.errors)
    else:
        assert serializer.is_valid(), serializer.errors
        for name, value in bounds.items():
            assert value is not None
            assert serializer.validated_data[name] == dt.datetime.fromisoformat(value)


@pytest.mark.parametrize(
    "placeholder,value,error",
    [
        ("data_interval_start", "2025-01-01T00:00:00Z", None),
        ("data_interval_start", "2026-01-09T00:00:00Z", "in the future"),
        ("data_interval_end", "2025-01-01T00:00:00Z", None),
        ("data_interval_end", "2026-01-09T00:00:00Z", "in the future"),
    ],
    ids=["old-start", "future-start", "old-end", "future-end"],
)
@time_machine.travel("2026-01-08T00:00:00Z", tick=False)
def test_single_download_bound_validation(placeholder: str, value: str, error: str | None) -> None:
    serializer = FileDownloadCountRowsRequestSerializer(
        data={"model": "hogql", "hogql_query": f"SELECT {{{placeholder}}} AS bound", placeholder: value}
    )

    if error:
        assert not serializer.is_valid()
        assert error in str(serializer.errors)
    else:
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data[placeholder] == dt.datetime.fromisoformat(value)


@pytest.mark.parametrize("model", ["events", "persons", "sessions"])
@pytest.mark.parametrize("bound", ["data_interval_start", "data_interval_end"])
def test_non_hogql_downloads_require_both_bounds(model: str, bound: str) -> None:
    serializer = FileDownloadBatchExportOnDemandSerializer(
        data={"model": model, "file": {"format": "Parquet"}, bound: "2026-01-01T00:00:00Z"}
    )

    assert not serializer.is_valid()
    assert "'data_interval_start' and 'data_interval_end' are required" in str(serializer.errors)


def test_placeholder_like_text_does_not_require_download_bounds() -> None:
    serializer = FileDownloadCountRowsRequestSerializer(
        data={"model": "hogql", "hogql_query": "SELECT '{data_interval_start}' AS value /* {data_interval_end} */"}
    )

    assert serializer.is_valid(), serializer.errors

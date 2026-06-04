import datetime as dt

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.generated_configs import GoogleSearchConsoleSourceConfig
from posthog.temporal.data_imports.sources.google_search_console.google_search_console import (
    FRESHNESS_LAG_DAYS,
    HISTORY_DAYS,
    GoogleSearchConsoleResumeConfig,
    _initial_start_date,
    _iter_dates,
    _resolve_window,
    _row_to_dict,
    google_search_console_source,
)

TODAY = dt.date(2026, 4, 30)


@pytest.mark.parametrize(
    "last_value,expected_start",
    [
        # No last value → full history window from today backwards.
        (None, _initial_start_date(TODAY)),
        # Very old last value → clamped to the history floor.
        (TODAY - dt.timedelta(days=10_000), _initial_start_date(TODAY)),
        # Recent date → used as-is.
        (TODAY - dt.timedelta(days=10), TODAY - dt.timedelta(days=10)),
        # ISO string is accepted and parsed.
        ("2026-04-15", dt.date(2026, 4, 15)),
        # Datetime is accepted and truncated to its date.
        (dt.datetime(2026, 4, 15, 12, 0, 0), dt.date(2026, 4, 15)),
    ],
)
def test_resolve_window_start(last_value, expected_start):
    start, end = _resolve_window(TODAY, last_value)
    assert start == expected_start
    assert end == TODAY - dt.timedelta(days=FRESHNESS_LAG_DAYS)


def test_resolve_window_full_history_spans_history_days():
    # Sanity-check the constant — the no-last-value start is exactly `HISTORY_DAYS` back.
    start, _ = _resolve_window(TODAY, None)
    assert (TODAY - start).days == HISTORY_DAYS


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (
            dt.date(2026, 4, 1),
            dt.date(2026, 4, 3),
            [dt.date(2026, 4, 1), dt.date(2026, 4, 2), dt.date(2026, 4, 3)],
        ),
        # start > end yields no dates.
        (dt.date(2026, 4, 5), dt.date(2026, 4, 1), []),
    ],
)
def test_iter_dates(start, end, expected):
    assert list(_iter_dates(start, end)) == expected


def test_row_to_dict_with_date_and_query():
    row = {"keys": ["2026-04-15", "posthog"], "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 4.5}
    out = _row_to_dict(row, ["date", "query"])

    assert out["date"] == dt.date(2026, 4, 15)
    assert out["query"] == "posthog"
    assert out["clicks"] == 10
    assert out["impressions"] == 100
    assert out["ctr"] == pytest.approx(0.1)
    assert out["position"] == pytest.approx(4.5)


def test_row_to_dict_handles_missing_metrics():
    out = _row_to_dict({"keys": ["2026-04-15"]}, ["date"])
    assert out["clicks"] == 0
    assert out["impressions"] == 0
    assert out["ctr"] == 0.0
    assert out["position"] == 0.0


def test_row_to_dict_injects_iter_date_when_date_not_in_dimensions():
    # `searchAppearance` schema can't include date in its API request, so the iterator
    # supplies the date externally to keep the per-day partition.
    row = {"keys": ["RICH_RESULT"], "clicks": 5, "impressions": 50, "ctr": 0.1, "position": 3.0}
    out = _row_to_dict(row, ["searchAppearance"], iter_date=dt.date(2026, 4, 15))

    assert out["date"] == dt.date(2026, 4, 15)
    assert out["searchAppearance"] == "RICH_RESULT"


def test_row_to_dict_prefers_api_date_over_iter_date():
    # When date IS in dimensions, the API's value wins — iter_date is a fallback only.
    row = {"keys": ["2026-04-15", "posthog"], "clicks": 1, "impressions": 1, "ctr": 1.0, "position": 1.0}
    out = _row_to_dict(row, ["date", "query"], iter_date=dt.date(1999, 1, 1))

    assert out["date"] == dt.date(2026, 4, 15)


def _make_response(config: GoogleSearchConsoleSourceConfig, rows_per_call: list[list[dict]]):
    """Build a SourceResponse where _query_search_analytics returns the given pages in order."""
    inputs = mock.MagicMock()
    inputs.team_id = 1
    inputs.job_id = "job-1"

    manager = mock.MagicMock()
    manager.can_resume.return_value = False

    saved_states: list[GoogleSearchConsoleResumeConfig] = []
    manager.save_state.side_effect = lambda state: saved_states.append(state)

    response = google_search_console_source(
        config=config,
        resource_name="search_analytics_by_date",
        team_id=1,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 25),
    )
    return response, manager, saved_states


def test_source_yields_rows_and_advances_dates(monkeypatch):
    config = GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )

    fake_today = dt.date(2026, 4, 30)
    pages_per_date: dict[str, list[list[dict]]] = {
        "2026-04-25": [[{"keys": ["2026-04-25"], "clicks": 1, "impressions": 5, "ctr": 0.2, "position": 3.0}]],
        "2026-04-26": [[{"keys": ["2026-04-26"], "clicks": 2, "impressions": 6, "ctr": 0.33, "position": 2.5}]],
        "2026-04-27": [[]],
    }
    end_date = fake_today - dt.timedelta(days=FRESHNESS_LAG_DAYS)
    # Fill any remaining dates with empty pages
    cursor = dt.date(2026, 4, 25)
    while cursor <= end_date:
        pages_per_date.setdefault(cursor.isoformat(), [[]])
        cursor += dt.timedelta(days=1)

    queries: list[tuple[str, int]] = []

    def fake_query(session, site_url, start_date, end_date, dimensions, start_row, row_limit=25000):
        queries.append((start_date, start_row))
        pages = pages_per_date.get(start_date, [[]])
        return pages.pop(0) if pages else []

    response, _manager, saved_states = _make_response(config, [])

    monkeypatch.setattr(
        "posthog.temporal.data_imports.sources.google_search_console.google_search_console._today",
        lambda: fake_today,
    )
    monkeypatch.setattr(
        "posthog.temporal.data_imports.sources.google_search_console.google_search_console.google_search_console_session",
        lambda *a, **kw: mock.MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.data_imports.sources.google_search_console.google_search_console._query_search_analytics",
        fake_query,
    )

    batches = list(response.items())

    yielded_dates = [batch[0]["date"] for batch in batches]
    assert dt.date(2026, 4, 25) in yielded_dates
    assert dt.date(2026, 4, 26) in yielded_dates
    # Each non-empty date that had a single page advances state to the *next* date with start_row=0
    advance_to_next_states = [s for s in saved_states if s.start_row == 0]
    assert any(s.current_date == "2026-04-26" for s in advance_to_next_states)
    assert any(s.current_date == "2026-04-27" for s in advance_to_next_states)


def test_source_resumes_from_saved_state(monkeypatch):
    config = GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )

    fake_today = dt.date(2026, 4, 30)
    queries: list[tuple[str, int]] = []

    def fake_query(session, site_url, start_date, end_date, dimensions, start_row, row_limit=25000):
        queries.append((start_date, start_row))
        return []

    manager = mock.MagicMock()
    manager.can_resume.return_value = True
    manager.load_state.return_value = GoogleSearchConsoleResumeConfig(current_date="2026-04-26", start_row=5000)

    monkeypatch.setattr(
        "posthog.temporal.data_imports.sources.google_search_console.google_search_console._today",
        lambda: fake_today,
    )
    monkeypatch.setattr(
        "posthog.temporal.data_imports.sources.google_search_console.google_search_console.google_search_console_session",
        lambda *a, **kw: mock.MagicMock(),
    )
    monkeypatch.setattr(
        "posthog.temporal.data_imports.sources.google_search_console.google_search_console._query_search_analytics",
        fake_query,
    )

    response = google_search_console_source(
        config=config,
        resource_name="search_analytics_by_date",
        team_id=1,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 1),
    )

    list(response.items())  # type: ignore[arg-type]

    # Earliest query should be the resumed date+offset
    assert queries[0] == ("2026-04-26", 5000)
    # No queries at earlier dates
    assert all(q[0] >= "2026-04-26" for q in queries)


def test_source_response_has_partition_metadata():
    config = GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )
    manager = mock.MagicMock()
    response = google_search_console_source(
        config=config,
        resource_name="search_analytics_by_query",
        team_id=1,
        resumable_source_manager=manager,
    )

    assert response.primary_keys == ["date", "query"]
    assert response.partition_keys == ["date"]
    assert response.partition_mode == "datetime"
    assert response.partition_format == "day"
    assert response.partition_count == 1
    assert response.partition_size == 1


def test_unknown_resource_name_raises():
    config = GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )
    with pytest.raises(ValueError, match="Unknown Google Search Console schema"):
        google_search_console_source(
            config=config,
            resource_name="not_a_real_schema",
            team_id=1,
            resumable_source_manager=mock.MagicMock(),
        )

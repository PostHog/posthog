from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from posthog.temporal.data_imports.sources.hubspot.hubspot import (
    HubspotPathologicalWindowError,
    HubspotResumeConfig,
    _backfill_associations_into_results,
    _batch_read_associations,
    _flatten_result,
    _iso_to_ms,
    _resolve_search_properties,
    get_rows_via_search,
    hubspot_source,
)
from posthog.temporal.data_imports.sources.hubspot.settings import (
    HUBSPOT_ENDPOINTS,
    SEARCH_PAGE_SIZE,
    SEARCH_RESULT_CAP,
)


def _make_response(status: int, payload: dict[str, Any] | None = None, text: str = "") -> MagicMock:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = text
    response.json.return_value = payload or {}
    response.raise_for_status.side_effect = None if response.ok else Exception(f"HTTP {status}")
    return response


def _make_manager(can_resume: bool = False, resume_state: HubspotResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = resume_state
    return manager


def _search_page(results: list[dict[str, Any]], after: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"results": results}
    if after is not None:
        payload["paging"] = {"next": {"after": after}}
    return payload


def _result(id_: str, cursor_value_ms: int, cursor_prop: str = "hs_lastmodifieddate") -> dict[str, Any]:
    # Shape mirrors HubSpot's v3 search API response. Properties are ISO strings.
    iso = datetime.fromtimestamp(cursor_value_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return {
        "id": id_,
        "properties": {
            "hs_object_id": id_,
            cursor_prop: iso,
        },
        "updatedAt": iso,
        "createdAt": iso,
    }


@pytest.fixture(autouse=True)
def _stub_property_names():
    with patch(
        "posthog.temporal.data_imports.sources.hubspot.hubspot._get_property_names",
        return_value=[],
    ):
        yield


class TestFlattenResult:
    def test_flattens_properties_to_top_level(self) -> None:
        row = _flatten_result({"id": "1", "properties": {"name": "acme", "hs_object_id": "1"}})
        assert row["name"] == "acme"
        assert row["hs_object_id"] == "1"

    def test_preserves_id_when_absent_in_properties(self) -> None:
        row = _flatten_result({"id": "abc", "properties": {"foo": "bar"}})
        assert row["id"] == "abc"
        assert row["foo"] == "bar"

    def test_builds_association_values(self) -> None:
        row = _flatten_result(
            {
                "id": "1",
                "properties": {"hs_object_id": "1"},
                "associations": {"deals": {"results": [{"id": "9", "type": "contact_to_deal"}]}},
            }
        )
        assert row["deals"] == [{"value": "1", "deals_id": "9"}]

    def test_no_associations_returns_without_key(self) -> None:
        row = _flatten_result({"id": "1", "properties": {"hs_object_id": "1"}})
        assert "deals" not in row


class TestIsoToMs:
    def test_none(self) -> None:
        assert _iso_to_ms(None) is None

    def test_int(self) -> None:
        assert _iso_to_ms(1_700_000_000_000) == 1_700_000_000_000

    def test_datetime_aware(self) -> None:
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        assert _iso_to_ms(dt) == int(dt.timestamp() * 1000)

    def test_datetime_naive_treated_as_utc(self) -> None:
        naive = datetime(2024, 1, 15, 12, 0, 0)
        expected = int(naive.replace(tzinfo=UTC).timestamp() * 1000)
        assert _iso_to_ms(naive) == expected

    def test_iso_string_with_z(self) -> None:
        assert _iso_to_ms("2024-01-15T12:00:00.000Z") == int(
            datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC).timestamp() * 1000
        )

    def test_iso_string_with_offset(self) -> None:
        # +00:00 is equivalent to Z
        assert _iso_to_ms("2024-01-15T12:00:00.000+00:00") == int(
            datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC).timestamp() * 1000
        )

    def test_digit_string_passthrough(self) -> None:
        assert _iso_to_ms("1700000000000") == 1_700_000_000_000

    def test_invalid_string_returns_none(self) -> None:
        assert _iso_to_ms("not a date") is None


class TestResolveSearchProperties:
    def test_force_includes_required(self) -> None:
        props, expected = _resolve_search_properties(
            api_key="k",
            refresh_token="r",
            endpoint="deals",
            object_type="deal",
            selected_properties=["amount"],
            include_custom_props=False,
            required_props=["hs_lastmodifieddate", "hs_object_id"],
            logger=MagicMock(),
            source_id=None,
        )
        assert "hs_lastmodifieddate" in props
        assert "hs_object_id" in props
        assert "amount" in props
        assert expected == props

    def test_defaults_include_cursor(self) -> None:
        props, _ = _resolve_search_properties(
            api_key="k",
            refresh_token="r",
            endpoint="deals",
            object_type="deal",
            selected_properties=None,
            include_custom_props=False,
            required_props=["hs_lastmodifieddate", "hs_object_id"],
            logger=MagicMock(),
            source_id=None,
        )
        # DEFAULT_DEAL_PROPS already contains hs_lastmodifieddate and hs_object_id; no duplication
        assert props.count("hs_lastmodifieddate") == 1
        assert props.count("hs_object_id") == 1

    def test_no_duplicate_when_selected_already_contains_required(self) -> None:
        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot._get_property_names",
            return_value=["amount", "hs_lastmodifieddate", "hs_object_id"],
        ):
            props, _ = _resolve_search_properties(
                api_key="k",
                refresh_token="r",
                endpoint="deals",
                object_type="deal",
                selected_properties=["amount", "hs_lastmodifieddate", "hs_object_id"],
                include_custom_props=False,
                required_props=["hs_lastmodifieddate", "hs_object_id"],
                logger=MagicMock(),
                source_id=None,
            )
        assert props.count("hs_lastmodifieddate") == 1
        assert props.count("hs_object_id") == 1

    def test_invalid_selected_ignored(self) -> None:
        logger = MagicMock()
        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot._get_property_names",
            return_value=["amount"],
        ):
            props, _ = _resolve_search_properties(
                api_key="k",
                refresh_token="r",
                endpoint="deals",
                object_type="deal",
                selected_properties=["amount", "not_real"],
                include_custom_props=False,
                required_props=["hs_lastmodifieddate"],
                logger=logger,
                source_id=None,
            )
        assert "not_real" not in props
        assert "amount" in props
        logger.warning.assert_called()


class TestBatchReadAssociations:
    def test_empty_ids_returns_empty(self) -> None:
        result = _batch_read_associations(
            from_entity_plural="contacts",
            to_entity_plural="deals",
            ids=[],
            headers={"authorization": "Bearer x"},
            refresh_token="r",
            source_id=None,
            logger=MagicMock(),
        )
        assert result == {}

    def test_posts_correct_body(self) -> None:
        calls = []

        def _post(url, headers=None, json=None, timeout=None):  # noqa: ARG001
            calls.append({"url": url, "json": json})
            return _make_response(
                200,
                {"results": [{"from": {"id": "1"}, "to": [{"toObjectId": 9, "associationTypes": [{"label": "x"}]}]}]},
            )

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(_post)})(),
        ):
            result = _batch_read_associations(
                from_entity_plural="contacts",
                to_entity_plural="deals",
                ids=["1", "2", "3"],
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
            )

        assert calls[0]["url"].endswith("/crm/v4/associations/contacts/deals/batch/read")
        assert calls[0]["json"] == {"inputs": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}
        assert result["1"] == [{"id": "9", "type": "x"}]

    def test_splits_into_chunks_of_batch_size(self) -> None:
        posts = []

        def _post(url, headers=None, json=None, timeout=None):  # noqa: ARG001
            posts.append(json)
            return _make_response(200, {"results": []})

        from posthog.temporal.data_imports.sources.hubspot.settings import ASSOCIATIONS_BATCH_SIZE

        ids = [str(i) for i in range(ASSOCIATIONS_BATCH_SIZE * 2 + 5)]
        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(_post)})(),
        ):
            _batch_read_associations(
                from_entity_plural="contacts",
                to_entity_plural="deals",
                ids=ids,
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
            )

        assert len(posts) == 3
        assert len(posts[0]["inputs"]) == ASSOCIATIONS_BATCH_SIZE
        assert len(posts[1]["inputs"]) == ASSOCIATIONS_BATCH_SIZE
        assert len(posts[2]["inputs"]) == 5

    def test_404_treated_as_empty(self) -> None:
        _resp = _make_response(404, {"message": "not found"})
        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(lambda *a, **k: _resp)})(),
        ):
            result = _batch_read_associations(
                from_entity_plural="contacts",
                to_entity_plural="deals",
                ids=["1"],
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
            )
        assert result == {}


class TestBackfillAssociations:
    def test_noop_when_no_association_types(self) -> None:
        results = [{"id": "1"}]
        _backfill_associations_into_results(
            results=results,
            from_entity_plural="deals",
            association_types=[],
            headers={"authorization": "Bearer x"},
            refresh_token="r",
            source_id=None,
            logger=MagicMock(),
        )
        assert "associations" not in results[0]

    def test_hydrates_associations_in_v3_shape(self) -> None:
        results: list[dict[str, Any]] = [{"id": "1"}]
        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations",
            return_value={"1": [{"id": "9", "type": "x"}]},
        ):
            _backfill_associations_into_results(
                results=results,
                from_entity_plural="contacts",
                association_types=["deals"],
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
            )
        assert results[0]["associations"] == {"deals": {"results": [{"id": "9", "type": "x"}]}}

    def test_handles_missing_id_gracefully(self) -> None:
        # ids-less results just don't get associations attached; no crash
        results: list[dict[str, Any]] = [{}, {"id": "2"}]
        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations",
            return_value={"2": [{"id": "7", "type": "y"}]},
        ):
            _backfill_associations_into_results(
                results=results,
                from_entity_plural="contacts",
                association_types=["deals"],
                headers={"authorization": "Bearer x"},
                refresh_token="r",
                source_id=None,
                logger=MagicMock(),
            )
        assert results[1]["associations"]["deals"]["results"] == [{"id": "7", "type": "y"}]


# Freeze "now" across search tests so window math is deterministic.
_FIXED_NOW_MS = 1_800_000_000_000  # 2027-01-15 08:00 UTC-ish
# Default seed that's within one window of `_FIXED_NOW_MS` so tests only iterate one window
# unless they deliberately want more.
_RECENT_SEED_MS = _FIXED_NOW_MS - (10 * 24 * 60 * 60 * 1000)
_RECENT_SEED_ISO = datetime.fromtimestamp(_RECENT_SEED_MS / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _setup_search_post(responses: list[Any]) -> tuple[Callable[..., Any], list[dict[str, Any]]]:
    """Return (side_effect_callable, captured_requests)."""
    captured: list[dict[str, Any]] = []
    iter_responses = iter(responses)

    def _post(url, headers=None, json=None, timeout=None):  # noqa: ARG001
        captured.append({"url": url, "json": dict(json or {})})
        return next(iter_responses)

    return _post, captured


class TestGetRowsViaSearch:
    def test_single_window_single_page_no_associations(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        rows = [_result("1", 1_799_000_000_000), _result("2", 1_799_500_000_000)]
        side_effect, captured = _setup_search_post([_make_response(200, _search_page(rows))])

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                )
            )

        assert len(captured) == 1
        body = captured[0]["json"]
        assert body["sorts"] == [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}]
        assert body["limit"] == SEARCH_PAGE_SIZE
        assert body["filterGroups"][0]["filters"][0]["propertyName"] == "hs_lastmodifieddate"
        assert body["filterGroups"][0]["filters"][0]["operator"] == "GTE"
        assert body["filterGroups"][0]["filters"][1]["operator"] == "LTE"
        assert "after" not in body

    def test_seed_from_db_incremental_field_last_value(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, captured = _setup_search_post([_make_response(200, _search_page([]))])

        seed_iso = (
            datetime.fromtimestamp((_FIXED_NOW_MS - 5 * 24 * 60 * 60 * 1000) / 1000, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3]
            + "Z"
        )

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=seed_iso,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                )
            )

        seed_ms = _iso_to_ms(seed_iso)
        assert seed_ms is not None
        # First filter's GTE should be seed_ms + 1 so we don't re-include the last synced record
        gte = int(captured[0]["json"]["filterGroups"][0]["filters"][0]["value"])
        assert gte == seed_ms + 1

    def test_resume_from_search_state_overrides_seed(self) -> None:
        # Narrow window so only one request is needed for the remaining range.
        end = _FIXED_NOW_MS
        start = end - (5 * 24 * 60 * 60 * 1000)
        last = start + (2 * 24 * 60 * 60 * 1000)
        resume = HubspotResumeConfig(
            sync_start_ms=start,
            sync_end_ms=end,
            last_cursor_ms=last,
        )
        manager = _make_manager(can_resume=True, resume_state=resume)
        logger = MagicMock()
        side_effect, captured = _setup_search_post([_make_response(200, _search_page([]))])

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value="2024-01-01T00:00:00.000Z",  # ignored on resume
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS + 999_999_999,  # ignored on resume (sync_end_ms from state wins)
                )
            )

        body = captured[0]["json"]
        assert int(body["filterGroups"][0]["filters"][0]["value"]) == last + 1  # last_cursor_ms + 1
        assert int(body["filterGroups"][0]["filters"][1]["value"]) == end  # sync_end_ms from state, not now_ms

    def test_ignores_next_url_resume_state(self) -> None:
        # A stale next_url from the GET path should not leak into the search path.
        resume = HubspotResumeConfig(next_url="https://stale.example/get")
        manager = _make_manager(can_resume=True, resume_state=resume)
        logger = MagicMock()
        side_effect, captured = _setup_search_post([_make_response(200, _search_page([]))])

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                )
            )

        # First request must start from STARTDATE (or equivalent), not the stale next_url.
        assert captured[0]["url"].endswith("/crm/v3/objects/deals/search")

    def test_multiple_windows_advance(self) -> None:
        # 90 days of range → 3 windows of 30 days.
        ninety_days_ms = 90 * 24 * 60 * 60 * 1000
        sync_end = _FIXED_NOW_MS
        sync_start_iso = (
            datetime.fromtimestamp((sync_end - ninety_days_ms) / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            + "Z"
        )

        manager = _make_manager()
        logger = MagicMock()
        # Three empty windows → three requests
        side_effect, captured = _setup_search_post(
            [
                _make_response(200, _search_page([])),
                _make_response(200, _search_page([])),
                _make_response(200, _search_page([])),
            ]
        )

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=sync_start_iso,
                    include_custom_props=False,
                    now_ms=sync_end,
                )
            )

        assert len(captured) == 3
        # Lower bounds strictly ascending
        lowers = [int(c["json"]["filterGroups"][0]["filters"][0]["value"]) for c in captured]
        assert lowers[0] < lowers[1] < lowers[2]

    def test_pagination_via_after_within_window(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, captured = _setup_search_post(
            [
                _make_response(200, _search_page([_result("1", 1_799_000_000_000)], after="cursor-1")),
                _make_response(200, _search_page([_result("2", 1_799_500_000_000)])),
            ]
        )

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                )
            )

        assert len(captured) == 2
        assert "after" not in captured[0]["json"]
        assert captured[1]["json"]["after"] == "cursor-1"

    def test_hits_10k_cap_and_subdivides(self) -> None:
        # Use cursor values within the seeded sync range so the fake server matches reality.
        cursor_base = _RECENT_SEED_MS + 10_000

        first_window_pages: list[dict[str, Any]] = []
        pages_in_cap = SEARCH_RESULT_CAP // SEARCH_PAGE_SIZE
        for i in range(pages_in_cap):
            batch = [
                _result(str(i * SEARCH_PAGE_SIZE + j), cursor_base + (i * SEARCH_PAGE_SIZE + j))
                for j in range(SEARCH_PAGE_SIZE)
            ]
            is_last = i == pages_in_cap - 1
            first_window_pages.append(_search_page(batch, after=None if is_last else f"c{i}"))

        # After the sub-slice kicks in, a small tail page with a record at a higher cursor.
        tail = [_result("tail-1", cursor_base + SEARCH_RESULT_CAP + 1_000)]
        responses = [_make_response(200, p) for p in first_window_pages] + [_make_response(200, _search_page(tail))]

        side_effect, captured = _setup_search_post(responses)
        manager = _make_manager()
        logger = MagicMock()

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                )
            )

        assert len(captured) >= pages_in_cap + 1

        # The request immediately after the cap was reached must have no `after` token,
        # and its GTE must equal the max cursor seen in the capped sub-slice.
        subslice_request = captured[pages_in_cap]
        assert "after" not in subslice_request["json"]
        first_lower = int(captured[0]["json"]["filterGroups"][0]["filters"][0]["value"])
        subslice_lower = int(subslice_request["json"]["filterGroups"][0]["filters"][0]["value"])
        assert subslice_lower > first_lower
        assert subslice_lower == cursor_base + SEARCH_RESULT_CAP - 1

    def test_pathological_window_raises(self) -> None:
        # SEARCH_RESULT_CAP records all with the same cursor_ms → can't sub-divide.
        identical_cursor = 1_799_000_000_000
        pages_in_cap = SEARCH_RESULT_CAP // SEARCH_PAGE_SIZE
        pages = []
        for i in range(pages_in_cap):
            batch = [_result(str(i * SEARCH_PAGE_SIZE + j), identical_cursor) for j in range(SEARCH_PAGE_SIZE)]
            is_last = i == pages_in_cap - 1
            pages.append(_search_page(batch, after=None if is_last else f"c{i}"))

        side_effect, _ = _setup_search_post([_make_response(200, p) for p in pages])
        manager = _make_manager()
        logger = MagicMock()

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            with pytest.raises(HubspotPathologicalWindowError):
                # Force a narrow sync window so the identical cursors trigger the cap check.
                list(
                    get_rows_via_search(
                        api_key="k",
                        refresh_token="r",
                        endpoint="deals",
                        logger=logger,
                        resumable_source_manager=manager,
                        db_incremental_field_last_value=str(identical_cursor - 1),
                        include_custom_props=False,
                        now_ms=identical_cursor + 1_000,
                    )
                )

    def test_saves_progress_at_window_boundaries(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, _ = _setup_search_post(
            [
                _make_response(200, _search_page([])),
                _make_response(200, _search_page([])),
            ]
        )

        sixty_days_ms = 60 * 24 * 60 * 60 * 1000
        sync_end = _FIXED_NOW_MS
        sync_start_iso = (
            datetime.fromtimestamp((sync_end - sixty_days_ms) / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
            + "Z"
        )

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=sync_start_iso,
                    include_custom_props=False,
                    now_ms=sync_end,
                )
            )

        # save_state should fire at least once per window advance
        assert manager.save_state.call_count >= 2
        last_saved = manager.save_state.call_args_list[-1].args[0]
        assert last_saved.sync_end_ms == sync_end
        assert last_saved.last_cursor_ms is not None and last_saved.last_cursor_ms >= last_saved.sync_start_ms

    def test_401_triggers_token_refresh_and_retry(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        responses = [
            _make_response(401, {"message": "unauthorized"}),
            _make_response(200, _search_page([])),
        ]
        side_effect, _ = _setup_search_post(responses)

        with (
            patch(
                "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
                new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
            ),
            patch(
                "posthog.temporal.data_imports.sources.hubspot.hubspot.hubspot_refresh_access_token",
                return_value="new-token",
            ) as refresh,
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                )
            )

        refresh.assert_called_once()

    def test_backfills_associations_for_contacts(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        # One page of contacts with an id placed inside the valid sync window.
        side_effect, _ = _setup_search_post(
            [
                _make_response(
                    200,
                    _search_page([_result("1", _RECENT_SEED_MS + 10_000, cursor_prop="lastmodifieddate")]),
                )
            ]
        )

        with (
            patch(
                "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
                new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
            ),
            patch(
                "posthog.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations",
                return_value={"1": [{"id": "9", "type": "t"}]},
            ) as mock_batch,
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="contacts",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                )
            )

        # One call per association type configured on contacts (deals, tickets, quotes)
        assoc_types_called = {c.kwargs["to_entity_plural"] for c in mock_batch.call_args_list}
        assert assoc_types_called == {"deals", "tickets", "quotes"}
        from_types = {c.kwargs["from_entity_plural"] for c in mock_batch.call_args_list}
        assert from_types == {"contacts"}
        # Ids are passed through as strings
        assert mock_batch.call_args_list[0].kwargs["ids"] == ["1"]

    def test_no_association_backfill_for_deals(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, _ = _setup_search_post([_make_response(200, _search_page([_result("1", 1_799_000_000_000)]))])

        with (
            patch(
                "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
                new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
            ),
            patch("posthog.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations") as mock_batch,
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                )
            )

        mock_batch.assert_not_called()

    def test_contacts_uses_lastmodifieddate_cursor(self) -> None:
        manager = _make_manager()
        logger = MagicMock()
        side_effect, captured = _setup_search_post([_make_response(200, _search_page([]))])

        with (
            patch(
                "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
                new=lambda *_a, **_k: type("_S", (), {"post": staticmethod(side_effect)})(),
            ),
            patch(
                "posthog.temporal.data_imports.sources.hubspot.hubspot._batch_read_associations",
                return_value={},
            ),
        ):
            list(
                get_rows_via_search(
                    api_key="k",
                    refresh_token="r",
                    endpoint="contacts",
                    logger=logger,
                    resumable_source_manager=manager,
                    db_incremental_field_last_value=_RECENT_SEED_ISO,
                    include_custom_props=False,
                    now_ms=_FIXED_NOW_MS,
                )
            )

        body = captured[0]["json"]
        assert body["sorts"][0]["propertyName"] == "lastmodifieddate"
        assert body["filterGroups"][0]["filters"][0]["propertyName"] == "lastmodifieddate"


class TestHubspotSourceRouting:
    def test_search_path_requires_cursor_property(self) -> None:
        # Temporarily strip the cursor property from `deals` config to exercise the guard.
        original = HUBSPOT_ENDPOINTS["deals"].cursor_filter_property_field
        HUBSPOT_ENDPOINTS["deals"].cursor_filter_property_field = None
        try:
            with pytest.raises(ValueError):
                hubspot_source(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=MagicMock(),
                    resumable_source_manager=MagicMock(),
                    use_search_path=True,
                )
        finally:
            HUBSPOT_ENDPOINTS["deals"].cursor_filter_property_field = original

    def test_search_path_happy_path(self) -> None:
        resp = hubspot_source(
            api_key="k",
            refresh_token="r",
            endpoint="deals",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            use_search_path=True,
            db_incremental_field_last_value=None,
        )
        # SourceResponse should be returned with partition settings preserved.
        assert resp.name == "deals"
        assert resp.primary_keys == ["id"]
        assert resp.partition_keys == [HUBSPOT_ENDPOINTS["deals"].partition_key]

    def test_get_path_fallback(self) -> None:
        resp = hubspot_source(
            api_key="k",
            refresh_token="r",
            endpoint="deals",
            logger=MagicMock(),
            resumable_source_manager=MagicMock(),
            use_search_path=False,
        )
        assert resp.name == "deals"


class TestGetRowsFullRefresh:
    """Smoke test that the GET path still works alongside the search path."""

    def test_paginates_via_next_url(self) -> None:
        from posthog.temporal.data_imports.sources.hubspot.hubspot import get_rows

        manager = _make_manager()
        logger = MagicMock()

        page1 = {
            "results": [{"id": "1", "properties": {"hs_object_id": "1"}}],
            "paging": {"next": {"link": "https://api.hubapi.com/page2"}},
        }
        page2 = {"results": [{"id": "2", "properties": {"hs_object_id": "2"}}]}

        iter_resp = iter([_make_response(200, page1), _make_response(200, page2)])
        captured_urls: list[str] = []

        def _get(url, headers=None, timeout=None):  # noqa: ARG001
            captured_urls.append(url)
            return next(iter_resp)

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"get": staticmethod(_get)})(),
        ):
            list(
                get_rows(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    include_custom_props=False,
                )
            )

        # Two calls: the constructed initial URL and the next_url from paging.
        assert len(captured_urls) == 2
        assert captured_urls[1] == "https://api.hubapi.com/page2"

    def test_resume_from_next_url(self) -> None:
        from posthog.temporal.data_imports.sources.hubspot.hubspot import get_rows

        resume = HubspotResumeConfig(next_url="https://api.hubapi.com/resume-here")
        manager = _make_manager(can_resume=True, resume_state=resume)
        logger = MagicMock()

        captured_urls: list[str] = []

        def _get(url, headers=None, timeout=None):  # noqa: ARG001
            captured_urls.append(url)
            return _make_response(200, {"results": [{"id": "5", "properties": {"hs_object_id": "5"}}]})

        with patch(
            "posthog.temporal.data_imports.sources.hubspot.hubspot.make_tracked_session",
            new=lambda *_a, **_k: type("_S", (), {"get": staticmethod(_get)})(),
        ):
            list(
                get_rows(
                    api_key="k",
                    refresh_token="r",
                    endpoint="deals",
                    logger=logger,
                    resumable_source_manager=manager,
                    include_custom_props=False,
                )
            )

        assert captured_urls[0] == "https://api.hubapi.com/resume-here"


class TestExpectedPropertiesBackfill:
    def test_cursor_column_present_on_row_after_flatten(self) -> None:
        # The pipeline tracks the cursor column by reading a field from the flattened row.
        # Assert that after _flatten_result, the cursor property sits at the top level.
        r = _result("1", 1_800_000_000_000, cursor_prop="hs_lastmodifieddate")
        row = _flatten_result(r)
        assert "hs_lastmodifieddate" in row

        contact = _result("2", 1_800_000_000_000, cursor_prop="lastmodifieddate")
        row2 = _flatten_result(contact)
        assert "lastmodifieddate" in row2

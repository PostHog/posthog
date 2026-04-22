import typing
import datetime as dt
from collections.abc import Iterable
from functools import partial

import pytest
from unittest import mock

import pyarrow as pa

from posthog.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from posthog.temporal.data_imports.sources.generated_configs import LinkedinAdsSourceConfig
from posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads import (
    LinkedInAdsResumeConfig,
    LinkedinAdsSchema,
    _convert_date_object_to_date,
    _convert_timestamp_to_date,
    _extract_type_and_id_from_urn,
    _flatten_linkedin_record,
    linkedin_ads_client,
    linkedin_ads_source,
)

from products.data_warehouse.backend.types import IncrementalFieldType


def _make_resume_manager(can_resume: bool = False, loaded_state: object = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = loaded_state
    return manager


def _small_batcher_factory(chunk_size: int):
    """Return a factory that builds a real Batcher with a tiny chunk_size for tests that
    need to drive the chunk-boundary / resume-token interaction deterministically."""
    return partial(Batcher, chunk_size=chunk_size)


class TestLinkedinAdsHelperFunctions:
    """Test helper functions in linkedin_ads.py."""

    def test_extract_type_and_id_from_urn_valid(self):
        """Test extracting ID and type from valid LinkedIn URN."""
        urn = "urn:li:sponsoredCampaign:12345678"
        result = _extract_type_and_id_from_urn(urn)

        assert result == ("sponsoredCampaign", 12345678)

    def test_convert_date_object_to_date_valid(self):
        """Test converting LinkedIn date object to Python date."""
        date_obj = {"year": 2024, "month": 3, "day": 15}
        result = _convert_date_object_to_date(date_obj)

        assert result == dt.date(2024, 3, 15)

    def test_convert_date_object_to_date_invalid(self):
        """Test converting invalid date object returns None."""
        invalid_cases = [
            {"year": 2024, "month": 3},  # Missing day
            {},  # Empty dict
            None,
        ]

        for invalid_obj in invalid_cases:
            result = _convert_date_object_to_date(invalid_obj)
            assert result is None

    def test_convert_timestamp_to_date_valid(self):
        """Test converting LinkedIn timestamp to date."""
        timestamp_ms = 1709654400000
        last_modified = {"time": timestamp_ms}
        result = _convert_timestamp_to_date(last_modified)

        assert str(result) == "2024-03-05"


class TestFlattenLinkedinRecord:
    """Test _flatten_linkedin_record function."""

    def test_flatten_date_range(self):
        """Test flattening dateRange field."""
        record = {
            "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}, "end": {"year": 2024, "month": 1, "day": 31}}
        }
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["dateRange"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["date_start"] == dt.date(2024, 1, 1)
        assert result["date_end"] == dt.date(2024, 1, 31)

    def test_flatten_urn_columns(self):
        """Test flattening URN columns."""
        record = {
            "campaignGroup": "urn:li:sponsoredCampaignGroup:123456789",
            "campaign": "urn:li:sponsoredCampaign:987654321",
        }
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["campaignGroup", "campaign"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["campaign_group_id"] == 123456789
        assert result["campaign_id"] == 987654321

    def test_flatten_integer_fields(self):
        """Test conversion of integer fields."""
        record = {"impressions": 1000, "clicks": 50}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["impressions", "clicks"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["impressions"] == 1000
        assert result["clicks"] == 50

    @pytest.mark.parametrize(
        "field_name, raw_value, expected",
        [
            ("costInUsd", "25.50", 25.50),
            ("costInLocalCurrency", "30.75", 30.75),
            ("conversionValueInLocalCurrency", "12.34", 12.34),
        ],
    )
    def test_flatten_float_fields(self, field_name: str, raw_value: str, expected: float):
        record = {field_name: raw_value}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=[field_name],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result[field_name] == expected

    def test_flatten_change_audit_stamps(self):
        """Test flattening changeAuditStamps field."""
        record = {"changeAuditStamps": {"created": {"time": 1709654400000}, "lastModified": {"time": 1709740800000}}}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["changeAuditStamps"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert str(result["created_time"]) == "2024-03-05"
        assert str(result["last_modified_time"]) == "2024-03-06"

    def test_flatten_pivot_values(self):
        """Test flattening pivotValues field."""
        record = {"pivotValues": ["urn:li:sponsoredCampaign:555666777", "urn:li:sponsoredAccount:888999000"]}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["pivotValues"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=True,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["campaign_id"] == 555666777
        assert result["account_id"] == 888999000

    def test_flatten_complex_objects_to_json(self):
        """Test that complex objects are passed through as-is from API."""
        record = {"targetingCriteria": {"locations": ["US", "CA"], "ages": {"min": 25, "max": 65}}}
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["targetingCriteria"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        # API returns dict objects, pipeline handles JSON conversion later
        assert result["targetingCriteria"]["locations"] == ["US", "CA"]
        assert result["targetingCriteria"]["ages"]["min"] == 25

    def test_flatten_missing_field_returns_none(self):
        """Test missing fields return None."""
        record: dict[str, typing.Any] = {}  # Empty record
        schema = LinkedinAdsSchema(
            name="test",
            primary_keys=[],
            field_names=["missing_field"],
            partition_keys=[],
            partition_mode=None,
            partition_format=None,
            is_stats=False,
            partition_size=1,
        )

        result = _flatten_linkedin_record(record, schema)

        assert result["missing_field"] is None


@mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Integration")
class TestLinkedinAdsClientFunction:
    """Test linkedin_ads_client function."""

    def test_linkedin_ads_client_no_access_token(self, mock_integration_model):
        """Test client creation with no access token raises error."""
        mock_integration = mock.MagicMock()
        mock_integration.access_token = None
        mock_integration_model.objects.get.return_value = mock_integration

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")

        with pytest.raises(ValueError, match="LinkedIn Ads integration does not have an access token"):
            linkedin_ads_client(config, team_id=789)


@mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.linkedin_ads_client")
class TestLinkedinAdsSource:
    """Test linkedin_ads_source function."""

    def test_linkedin_ads_source_with_incremental(self, mock_client_func):
        """Test linkedin_ads_source with incremental field."""
        mock_client = mock.MagicMock()
        # Analytics endpoints are single-shot: one page, no next_page_token.
        mock_client.get_data_by_resource.return_value = [
            ([{"impressions": 1000, "dateRange": {"start": {"year": 2024, "month": 1, "day": 1}}}], None)
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager()

        result = linkedin_ads_source(
            config=config,
            resource_name="campaign_stats",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
            should_use_incremental_field=True,
            incremental_field="date_start",
            incremental_field_type=IncrementalFieldType.Date,
            db_incremental_field_last_value=dt.date(2024, 1, 1),
        )

        # Process the rows to trigger the client call
        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        # One final-flush pa.Table containing the single row.
        assert len(rows) == 1
        assert isinstance(rows[0], pa.Table)
        assert rows[0].num_rows == 1

        # Verify client was called with correct date parameters
        mock_client.get_data_by_resource.assert_called_once()
        call_args = mock_client.get_data_by_resource.call_args
        assert call_args[1]["date_start"] == "2024-01-01"
        assert call_args[1]["starting_page_token"] is None
        # Single-shot endpoints never save state (no next_page_token).
        manager.save_state.assert_not_called()

    def test_fresh_run_small_data_saves_no_state_until_durable_flush(self, mock_client_func):
        """Small total payload: nothing flushes mid-stream, so no resume state is saved.

        Saving a token before the yielded data is durably written would risk skipping it
        on resume. The final flush at end-of-stream is always the last thing before a
        clean completion, so there's no durable intermediate checkpoint to record.
        """
        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = [
            ([{"id": "c1"}], "token-2"),
            ([{"id": "c2"}], "token-3"),
            ([{"id": "c3"}], None),
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        # Default Batcher chunk_size (5000) means three tiny pages all land in one final flush.
        assert len(rows) == 1
        assert isinstance(rows[0], pa.Table)
        assert rows[0].num_rows == 3

        mock_client.get_data_by_resource.assert_called_once()
        assert mock_client.get_data_by_resource.call_args[1]["starting_page_token"] is None

        manager.save_state.assert_not_called()
        manager.load_state.assert_not_called()

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Batcher")
    def test_state_only_advances_past_fully_flushed_pages(self, mock_batcher_cls, mock_client_func):
        """Core safety property: the saved token must only point to pages whose rows are
        already durable (yielded as a flushed pa.Table). A page whose rows are still in
        the in-memory buffer must never have its `next_page_token` persisted, because a
        crash would otherwise leave those rows unwritten and unreachable on resume."""
        mock_batcher_cls.side_effect = _small_batcher_factory(chunk_size=2)

        mock_client = mock.MagicMock()
        # Two-record pages; with chunk_size=2 the batcher flushes whenever two records
        # have accumulated.
        mock_client.get_data_by_resource.return_value = [
            ([{"id": "p1-a"}, {"id": "p1-b"}], "token-2"),  # page 1 → fills buffer, flush, pending=None
            ([{"id": "p2-a"}, {"id": "p2-b"}], "token-3"),  # page 2 → fills buffer, flush, advances to token-2
            ([{"id": "p3-a"}, {"id": "p3-b"}], None),  # page 3 → fills buffer, flush, advances to token-3
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        assert all(isinstance(r, pa.Table) for r in rows)
        assert [r.num_rows for r in rows] == [2, 2, 2]

        # Flush order: (p1-a, p1-b) flush → nothing to commit yet; (p2-a, p2-b) flush →
        # commit token-2 (all of page 1 is durable); (p3-a, p3-b) flush → commit token-3
        # (all of page 2 is durable). token-3 is the last committed token because page 3
        # has no next_page_token.
        assert manager.save_state.call_args_list == [
            mock.call(LinkedInAdsResumeConfig(page_token="token-2")),
            mock.call(LinkedInAdsResumeConfig(page_token="token-3")),
        ]

    @mock.patch("posthog.temporal.data_imports.sources.linkedin_ads.linkedin_ads.Batcher")
    def test_state_does_not_advance_when_page_straddles_flush_boundary(self, mock_batcher_cls, mock_client_func):
        """When a page's records straddle a flush boundary, its `next_page_token` must
        stay pending until a later flush captures the remaining records — otherwise the
        still-buffered tail of that page would be lost on crash-recovery, yet the saved
        token would already point past it.

        The final incomplete-chunk flush intentionally does NOT commit a new token: if
        that write fails we want the most recent durably-flushed checkpoint to remain
        authoritative, so resume re-fetches from there."""
        mock_batcher_cls.side_effect = _small_batcher_factory(chunk_size=3)

        mock_client = mock.MagicMock()
        # Pages of 1, 2, 2 records. With chunk_size=3 the flush happens at the 3rd
        # record batched (the 2nd record of page 2), leaving the trailing record of
        # page 2 and all of page 3 in the buffer for the final incomplete-chunk flush.
        mock_client.get_data_by_resource.return_value = [
            ([{"id": "p1-a"}], "token-2"),
            ([{"id": "p2-a"}, {"id": "p2-b"}], "token-3"),
            ([{"id": "p3-a"}, {"id": "p3-b"}], None),
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        assert all(isinstance(r, pa.Table) for r in rows)
        # Flush 1 at p2-b: [p1-a, p2-a, p2-b] — page 1 fully durable, "token-2" saved.
        # Final flush: [p3-a, p3-b] — page 2's tail had already been written by flush 1,
        # page 3 never triggered its own mid-stream flush, and no new token is committed.
        assert [r.num_rows for r in rows] == [3, 2]

        # Critically, "token-3" is never saved — because the only flush that followed
        # the end of page 2's loop was the final incomplete-chunk flush, which
        # deliberately skips save_state. On crash mid-final-flush, resume from "token-2"
        # still recovers everything safely.
        assert manager.save_state.call_args_list == [
            mock.call(LinkedInAdsResumeConfig(page_token="token-2")),
        ]

    def test_resume_run_seeds_starting_page_token_and_skips_initial(self, mock_client_func):
        """Resume run: load_state is called; the saved token is passed as starting_page_token."""
        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = [
            ([{"id": "c2"}], None),
        ]
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=True, loaded_state=LinkedInAdsResumeConfig(page_token="token-2"))

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        assert len(rows) == 1
        assert isinstance(rows[0], pa.Table)
        assert rows[0].num_rows == 1
        assert rows[0].column("id").to_pylist() == ["c2"]

        manager.can_resume.assert_called_once()
        manager.load_state.assert_called_once()
        mock_client.get_data_by_resource.assert_called_once()
        assert mock_client.get_data_by_resource.call_args[1]["starting_page_token"] == "token-2"
        # Final page of a resume has no next token → no save.
        manager.save_state.assert_not_called()

    def test_empty_first_page_does_not_save_state(self, mock_client_func):
        """Empty first page (no next token): no yields, no save_state."""
        mock_client = mock.MagicMock()
        mock_client.get_data_by_resource.return_value = iter([])
        mock_client_func.return_value = mock_client

        config = LinkedinAdsSourceConfig(linkedin_ads_integration_id=123, account_id="456")
        manager = _make_resume_manager(can_resume=False)

        result = linkedin_ads_source(
            config=config,
            resource_name="campaigns",
            team_id=789,
            resumable_source_manager=manager,
            logger=mock.MagicMock(),
        )

        items = result.items()
        assert isinstance(items, Iterable)
        rows = list(items)
        assert rows == []
        manager.save_state.assert_not_called()

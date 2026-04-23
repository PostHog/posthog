import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import pytest
from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized
from requests import Response

from posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads import (
    TikTokAdsResumeConfig,
    get_tiktok_resource,
    tiktok_ads_source,
)
from posthog.temporal.data_imports.sources.tiktok_ads.utils import TikTokDateRangeManager, TikTokReportResource


def _make_manager(can_resume: bool = False, state: TikTokAdsResumeConfig | None = None) -> MagicMock:
    manager = MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


def _make_response(json_body: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(json_body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page_response(page: int, total_pages: int, items: list[dict[str, Any]]) -> Response:
    return _make_response(
        {
            "code": 0,
            "message": "OK",
            "data": {
                "list": items,
                "page_info": {
                    "page": page,
                    "page_size": 1000,
                    "total_page": total_pages,
                    "total_number": len(items) * total_pages,
                },
            },
        }
    )


class TestTikTokAdsHelpers:
    """Test suite for TikTok Ads helper functions."""

    def test_flatten_tiktok_report_record_nested(self):
        """Test flattening nested TikTok report structure."""
        nested_record = {
            "dimensions": {"campaign_id": "123456", "stat_time_day": "2025-09-27"},
            "metrics": {"clicks": "947", "impressions": "23241", "spend": "125.50"},
        }

        result = TikTokReportResource.transform_analytics_reports([nested_record])[0]

        expected = {
            "campaign_id": "123456",
            "stat_time_day": "2025-09-27",
            "clicks": "947",
            "impressions": "23241",
            "spend": "125.50",
        }

        assert result == expected

    def test_flatten_tiktok_report_record_flat(self):
        """Test flattening already flat record (entity endpoints)."""
        flat_record = {"campaign_id": "123456", "campaign_name": "Test Campaign", "status": "ENABLE"}

        result = TikTokReportResource.transform_entity_reports([flat_record])[0]
        expected = flat_record.copy()
        expected["current_status"] = "ACTIVE"
        assert result == expected

    def test_flatten_tiktok_reports(self):
        """Test batch flattening of TikTok reports."""
        reports = [
            {"dimensions": {"campaign_id": "123"}, "metrics": {"clicks": "100"}},
            {"dimensions": {"campaign_id": "456"}, "metrics": {"clicks": "200"}},
        ]

        result = TikTokReportResource.transform_analytics_reports(reports)

        expected = [{"campaign_id": "123", "clicks": "100"}, {"campaign_id": "456", "clicks": "200"}]

        assert result == expected

    @parameterized.expand(
        [
            ("no_incremental", False, None, 365),
            ("with_datetime", True, datetime.now() - timedelta(days=30), 30),
            ("with_date_string", True, (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"), 30),
            ("with_recent_date", True, datetime.now() - timedelta(days=2), 7),
            ("with_old_date", True, datetime.now() - timedelta(days=60), 60),
        ]
    )
    def test_get_incremental_date_range(self, name, should_use_incremental, last_value, expected_days_back):
        """Test incremental date range calculation."""
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(should_use_incremental, last_value)

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        days_diff = (end_dt - start_dt).days
        assert days_diff <= expected_days_back + 1

    def test_get_incremental_date_range_parse_error(self):
        """Test date range calculation with invalid last value."""
        start_date, end_date = TikTokDateRangeManager.get_incremental_range(True, "invalid_date")

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days_diff = (end_dt - start_dt).days

        assert days_diff <= 365

    @parameterized.expand(
        [
            (
                "single_chunk",
                (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
            (
                "two_chunks",
                (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                2,
            ),
            (
                "three_chunks",
                (datetime.now() - timedelta(days=89)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                3,
            ),
            (
                "exact_boundary",
                (datetime.now() - timedelta(days=29)).strftime("%Y-%m-%d"),
                datetime.now().strftime("%Y-%m-%d"),
                30,
                1,
            ),
        ]
    )
    def test_generate_date_chunks(self, name, start_date, end_date, chunk_days, expected_chunks):
        """Test date chunk generation."""
        chunks = TikTokDateRangeManager.generate_chunks(start_date, end_date, chunk_days)

        assert len(chunks) == expected_chunks

        for i, (chunk_start, chunk_end) in enumerate(chunks):
            chunk_start_dt = datetime.strptime(chunk_start, "%Y-%m-%d")
            chunk_end_dt = datetime.strptime(chunk_end, "%Y-%m-%d")

            assert (chunk_end_dt - chunk_start_dt).days <= chunk_days

            if i < len(chunks) - 1:
                next_chunk_start = datetime.strptime(chunks[i + 1][0], "%Y-%m-%d")
                assert (next_chunk_start - chunk_end_dt).days == 1


class TestGetResource:
    """Test suite for resource configuration generation."""

    def setup_method(self):
        self.advertiser_id = "123456789"

    def test_get_tiktok_resource_unknown_endpoint(self):
        with pytest.raises(ValueError, match="Unknown endpoint: invalid_endpoint"):
            get_tiktok_resource("invalid_endpoint", self.advertiser_id, False)

    def test_get_tiktok_resource_entity_endpoint(self):
        resource = get_tiktok_resource("campaigns", self.advertiser_id, False)

        assert resource["name"] == "campaigns"
        assert resource["table_name"] == "campaigns"
        assert resource["primary_key"] == ["campaign_id"]
        assert resource["write_disposition"] == "replace"

        assert resource["endpoint"]["params"]["advertiser_id"] == self.advertiser_id

    def test_get_tiktok_resource_report_endpoint_incremental(self):
        resource = get_tiktok_resource("campaign_report", self.advertiser_id, True)

        assert resource["name"] == "campaign_report"
        assert resource["table_name"] == "campaign_report"
        assert resource["primary_key"] == ["campaign_id", "stat_time_day"]
        assert isinstance(resource["write_disposition"], dict)
        write_disposition = resource["write_disposition"]
        assert write_disposition["disposition"] == "merge"
        assert write_disposition["strategy"] == "upsert"

        assert "start_date" in resource["endpoint"]["params"]
        assert "end_date" in resource["endpoint"]["params"]

    def test_get_tiktok_resource_report_endpoint_full_refresh(self):
        resource = get_tiktok_resource("campaign_report", self.advertiser_id, False)

        assert "start_date" in resource["endpoint"]["params"]
        assert "end_date" in resource["endpoint"]["params"]

        assert resource["endpoint"]["params"]["start_date"] == "{start_date}"
        assert resource["endpoint"]["params"]["end_date"] == "{end_date}"

    def test_get_tiktok_resource_with_date_chunking(self):
        resource = get_tiktok_resource("campaign_report", self.advertiser_id, True)

        assert "start_date" in resource["endpoint"]["params"]
        assert "end_date" in resource["endpoint"]["params"]

        assert resource["endpoint"]["params"]["start_date"] == "{start_date}"
        assert resource["endpoint"]["params"]["end_date"] == "{end_date}"


class TestTikTokAdsSource:
    """Test suite for main TikTok Ads source function."""

    def setup_method(self):
        self.advertiser_id = "123456789"
        self.team_id = 123
        self.job_id = str(uuid4())
        self.access_token = "test_access_token"

    @parameterized.expand(
        [
            ("campaigns", False, None),
            ("ad_groups", False, None),
            ("ads", False, None),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads.rest_api_resource")
    def test_tiktok_ads_source_entity_endpoints(
        self, endpoint, should_use_incremental, last_value, mock_rest_api_resource
    ):
        """Source returns a response with a callable items iterable for entity endpoints."""
        mock_dlt_resource = Mock()
        mock_dlt_resource.__iter__ = Mock(return_value=iter([{"campaign_id": "123", "name": "Test Campaign"}]))
        mock_rest_api_resource.return_value = mock_dlt_resource

        result = tiktok_ads_source(
            advertiser_id=self.advertiser_id,
            endpoint=endpoint,
            team_id=self.team_id,
            job_id=self.job_id,
            access_token=self.access_token,
            db_incremental_field_last_value=last_value,
            resumable_source_manager=_make_manager(can_resume=False),
            should_use_incremental_field=should_use_incremental,
        )

        assert result.name == endpoint
        assert result.items is not None
        assert result.partition_count == 1

    @parameterized.expand(
        [
            ("campaign_report", False, None),
            ("ad_group_report", False, None),
            ("ad_report", False, None),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads.rest_api_resource")
    def test_tiktok_ads_source_report_endpoints_full_refresh(
        self, endpoint, should_use_incremental, last_value, mock_rest_api_resource
    ):
        """Source returns a response for report endpoints with full refresh."""
        mock_dlt_resource = Mock()
        mock_dlt_resource.__iter__ = Mock(return_value=iter([{"campaign_id": "123", "clicks": "100"}]))
        mock_rest_api_resource.return_value = mock_dlt_resource

        result = tiktok_ads_source(
            advertiser_id=self.advertiser_id,
            endpoint=endpoint,
            team_id=self.team_id,
            job_id=self.job_id,
            access_token=self.access_token,
            db_incremental_field_last_value=last_value,
            resumable_source_manager=_make_manager(can_resume=False),
            should_use_incremental_field=should_use_incremental,
        )

        assert result.name == endpoint
        assert result.items is not None
        assert result.partition_count == 1

    @parameterized.expand(
        [
            ("campaign_report", True, datetime.now() - timedelta(days=5)),
            ("ad_group_report", True, (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")),
            ("ad_report", True, datetime.now() - timedelta(days=10)),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads.rest_api_resource")
    def test_tiktok_ads_source_report_endpoints_incremental(
        self, endpoint, should_use_incremental, last_value, mock_rest_api_resource
    ):
        """Source returns a response for report endpoints with incremental sync."""
        mock_dlt_resource = Mock()
        mock_dlt_resource.__iter__ = Mock(return_value=iter([{"campaign_id": "123", "clicks": "100"}]))
        mock_rest_api_resource.return_value = mock_dlt_resource

        result = tiktok_ads_source(
            advertiser_id=self.advertiser_id,
            endpoint=endpoint,
            team_id=self.team_id,
            job_id=self.job_id,
            access_token=self.access_token,
            db_incremental_field_last_value=last_value,
            resumable_source_manager=_make_manager(can_resume=False),
            should_use_incremental_field=should_use_incremental,
        )

        assert result.name == endpoint
        assert result.items is not None
        assert result.partition_count == 1

    def test_tiktok_ads_source_invalid_endpoint(self):
        with pytest.raises(KeyError):
            tiktok_ads_source(
                advertiser_id=self.advertiser_id,
                endpoint="invalid_endpoint",
                team_id=self.team_id,
                job_id=self.job_id,
                access_token=self.access_token,
                db_incremental_field_last_value=None,
                resumable_source_manager=_make_manager(can_resume=False),
                should_use_incremental_field=False,
            )


class TestTikTokAdsResumeBehavior:
    """End-to-end resume behavior with a mocked HTTP session."""

    def setup_method(self):
        self.advertiser_id = "123456789"
        self.team_id = 123
        self.job_id = "test_job"
        self.access_token = "test_access_token"

    def _run_campaigns(self, manager: MagicMock, responses: list[Response]) -> MagicMock:
        with patch(
            "posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session"
        ) as MockSession:
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = responses

            response = tiktok_ads_source(
                advertiser_id=self.advertiser_id,
                endpoint="campaigns",
                team_id=self.team_id,
                job_id=self.job_id,
                access_token=self.access_token,
                db_incremental_field_last_value=None,
                resumable_source_manager=manager,
                should_use_incremental_field=False,
            )
            # Drain the resource to exercise the pagination loop. The source
            # returns a sync iterable; cast to narrow the SourceResponse union.
            list(cast(Iterable[Any], response.items()))
            return mock_session

    def test_fresh_run_saves_state_after_each_non_terminal_page(self):
        """can_resume=False: first page yields, manager.save_state called with next page number."""
        manager = _make_manager(can_resume=False)

        responses = [
            _page_response(page=1, total_pages=3, items=[{"campaign_id": "c1"}]),
            _page_response(page=2, total_pages=3, items=[{"campaign_id": "c2"}]),
            _page_response(page=3, total_pages=3, items=[{"campaign_id": "c3"}]),
        ]
        self._run_campaigns(manager, responses)

        # State is persisted after every non-terminal page (2 saves for 3 pages).
        save_calls = manager.save_state.call_args_list
        assert len(save_calls) == 2

        first_save = save_calls[0].args[0]
        assert isinstance(first_save, TikTokAdsResumeConfig)
        assert first_save.chunk_index == 0
        assert first_save.page == 2

        second_save = save_calls[1].args[0]
        assert second_save.chunk_index == 0
        assert second_save.page == 3

    def test_resume_uses_saved_cursor(self):
        """can_resume=True: the first request targets the saved page, not page 1."""
        manager = _make_manager(
            can_resume=True,
            state=TikTokAdsResumeConfig(page=2, chunk_index=0),
        )

        responses = [
            _page_response(page=2, total_pages=2, items=[{"campaign_id": "c2"}]),
        ]
        mock_session = self._run_campaigns(manager, responses)

        sent_request = mock_session.send.call_args_list[0].args[0]
        # Only one request issued — initial page 1 is skipped.
        assert len(mock_session.send.call_args_list) == 1
        assert sent_request.url.endswith("/campaign/get/")
        # ``prepare_request`` is the identity so the Request's params dict is
        # what we care about: it must target page 2.
        assert sent_request.params["page"] == 2

    def test_terminal_page_does_not_save_state(self):
        """A single final page yields no save_state calls."""
        manager = _make_manager(can_resume=False)

        responses = [
            _page_response(page=1, total_pages=1, items=[{"campaign_id": "c1"}]),
        ]
        self._run_campaigns(manager, responses)

        manager.save_state.assert_not_called()

    def test_stale_resume_state_is_discarded(self):
        """A saved chunk_index beyond the current chunk list falls back to a fresh run."""
        manager = _make_manager(
            can_resume=True,
            state=TikTokAdsResumeConfig(page=4, chunk_index=99),
        )

        responses = [
            _page_response(page=1, total_pages=1, items=[{"campaign_id": "c1"}]),
        ]
        mock_session = self._run_campaigns(manager, responses)

        # Falls back to a fresh run that requests page 1.
        sent_request = mock_session.send.call_args_list[0].args[0]
        assert sent_request.params["page"] == 1


class TestTikTokAdsReportChunkResumeBehavior:
    """End-to-end resume behavior for chunked report endpoints."""

    def setup_method(self):
        self.advertiser_id = "123456789"
        self.team_id = 123
        self.job_id = "test_job"
        self.access_token = "test_access_token"

    def _report_chunks(self) -> list[dict[str, Any]]:
        """Build deterministic chunks using the production setup code.

        Uses a 58-day span and 29-day chunk size to produce exactly two
        29-day chunks. The test then extends this to three chunks below
        where multi-chunk skip/resume behavior is exercised.
        """
        base = get_tiktok_resource("campaign_report", self.advertiser_id, True)
        return TikTokReportResource.create_chunked_resources(
            base,
            start_date="2024-01-01",
            end_date="2024-03-30",  # 90 days -> 4 chunks at 29-day chunk size
            advertiser_id=self.advertiser_id,
        )

    def _run_report(self, manager: MagicMock, responses: list[Response]) -> MagicMock:
        with (
            patch(
                "posthog.temporal.data_imports.sources.common.rest_source.rest_client.requests.Session"
            ) as MockSession,
            patch(
                "posthog.temporal.data_imports.sources.tiktok_ads.tiktok_ads.TikTokReportResource.setup_report_resources",
                return_value=self._report_chunks(),
            ),
        ):
            mock_session = MockSession.return_value
            mock_session.headers = {}
            mock_session.prepare_request.side_effect = lambda req: req
            mock_session.send.side_effect = responses

            response = tiktok_ads_source(
                advertiser_id=self.advertiser_id,
                endpoint="campaign_report",
                team_id=self.team_id,
                job_id=self.job_id,
                access_token=self.access_token,
                db_incremental_field_last_value=None,
                resumable_source_manager=manager,
                should_use_incremental_field=True,
            )
            list(cast(Iterable[Any], response.items()))
            return mock_session

    def test_resume_from_middle_chunk_skips_earlier_and_runs_later_chunks_fresh(self):
        """Resuming into a non-first chunk:
        - chunks before the resumed one issue no HTTP requests,
        - the first request for the resumed chunk targets the saved page,
        - chunks after it start fresh at page 1.
        """
        chunks = self._report_chunks()
        assert len(chunks) >= 3, "need at least 3 chunks to exercise skip/resume/fresh"

        resume_idx = 1
        chunk_r = chunks[resume_idx]
        chunk_r_start = chunk_r["endpoint"]["params"]["start_date"]
        chunk_r_end = chunk_r["endpoint"]["params"]["end_date"]

        manager = _make_manager(
            can_resume=True,
            state=TikTokAdsResumeConfig(
                page=3,
                chunk_index=resume_idx,
                chunk_start_date=chunk_r_start,
                chunk_end_date=chunk_r_end,
            ),
        )

        # Resumed chunk: single terminal page at page=3. Subsequent chunks:
        # each resolves in one page.
        responses: list[Response] = [_page_response(page=3, total_pages=3, items=[{"campaign_id": "c-resume"}])]
        responses.extend(
            _page_response(page=1, total_pages=1, items=[{"campaign_id": f"c{i}"}])
            for i in range(resume_idx + 1, len(chunks))
        )
        mock_session = self._run_report(manager, responses)

        sent_requests = [c.args[0] for c in mock_session.send.call_args_list]
        # One request for the resumed chunk + one for each chunk after it.
        assert len(sent_requests) == 1 + (len(chunks) - resume_idx - 1)

        resumed_request = sent_requests[0]
        assert resumed_request.params["page"] == 3
        assert resumed_request.params["start_date"] == chunk_r_start
        assert resumed_request.params["end_date"] == chunk_r_end

        for req, chunk in zip(sent_requests[1:], chunks[resume_idx + 1 :], strict=True):
            assert req.params["page"] == 1
            assert req.params["start_date"] == chunk["endpoint"]["params"]["start_date"]

    def test_resume_falls_back_when_saved_chunk_dates_no_longer_match(self):
        """If the saved chunk's date range doesn't exist in the current chunk
        list (e.g. ``datetime.now()`` advanced and shifted the window), discard
        the state and start fresh from chunk 0, page 1."""
        manager = _make_manager(
            can_resume=True,
            state=TikTokAdsResumeConfig(
                page=5,
                chunk_index=1,
                chunk_start_date="1999-12-01",  # definitely not in any current chunk
                chunk_end_date="1999-12-29",
            ),
        )

        chunks = self._report_chunks()
        responses: list[Response] = [
            _page_response(page=1, total_pages=1, items=[{"campaign_id": f"c{i}"}]) for i in range(len(chunks))
        ]
        mock_session = self._run_report(manager, responses)

        sent_requests = [c.args[0] for c in mock_session.send.call_args_list]
        assert len(sent_requests) == len(chunks)
        for req in sent_requests:
            assert req.params["page"] == 1

    def test_fresh_run_save_state_includes_chunk_dates(self):
        """Fresh chunked run: save_state calls include the chunk's
        ``(start_date, end_date)`` so the saved state is stable across
        boundary-shifting re-runs."""
        chunks = self._report_chunks()
        chunk0_start = chunks[0]["endpoint"]["params"]["start_date"]
        chunk0_end = chunks[0]["endpoint"]["params"]["end_date"]

        manager = _make_manager(can_resume=False)

        responses: list[Response] = [
            # chunk 0: two pages (save expected after page 1, not after page 2).
            _page_response(page=1, total_pages=2, items=[{"campaign_id": "c0a"}]),
            _page_response(page=2, total_pages=2, items=[{"campaign_id": "c0b"}]),
        ]
        # Remaining chunks each resolve in a single page (no saves).
        responses.extend(
            _page_response(page=1, total_pages=1, items=[{"campaign_id": f"c{i}"}]) for i in range(1, len(chunks))
        )
        self._run_report(manager, responses)

        save_calls = manager.save_state.call_args_list
        assert len(save_calls) == 1
        saved: TikTokAdsResumeConfig = save_calls[0].args[0]
        assert saved.chunk_index == 0
        assert saved.page == 2
        assert saved.chunk_start_date == chunk0_start
        assert saved.chunk_end_date == chunk0_end

import base64
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest.mock import MagicMock

from django.test import override_settings

import dlt
import dagster
import requests
from parameterized import parameterized

from ee.billing.dags.lemlist import dag as lemlist_dag
from ee.billing.dags.lemlist.auth import LemlistAuthResource, LemlistNotConfiguredError
from ee.billing.dags.lemlist.dag import lemlist_campaigns_and_stats
from ee.billing.dags.lemlist.destination import build_pipeline
from ee.billing.dags.lemlist.source import (
    _fetch_stats_batch,
    _iter_campaign_pages,
    build_stats_payload,
    build_stats_row,
    chunk_ids,
    lemlist_source,
    normalize_campaign,
)
from ee.billing.salesforce_enrichment.duckgres_client import DuckgresNotConfiguredError


def _mock_json_response(payload: dict[str, Any]) -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = payload
    response.raise_for_status = MagicMock()
    return response


# --------------------------------------------------------------------------- #
# auth.py — LemlistAuthResource
# --------------------------------------------------------------------------- #


class TestLemlistAuthResource:
    def test_empty_api_key_raises(self):
        resource = LemlistAuthResource(api_key="")
        with pytest.raises(LemlistNotConfiguredError):
            resource.build_session()

    def test_build_session_sets_basic_auth_with_key_as_password(self):
        session = LemlistAuthResource(api_key="secret-key").build_session()
        assert isinstance(session.auth, requests.auth.HTTPBasicAuth)
        assert session.auth.username == ""
        assert session.auth.password == "secret-key"

    # Lemlist requires ``Basic base64(":<api_key>")`` — verify the header that
    # ``requests`` actually sends matches that byte-for-byte, not just that the
    # auth object carries the right pieces.
    def test_session_renders_authorization_header_per_lemlist_spec(self):
        session = LemlistAuthResource(api_key="secret-key").build_session()
        request = requests.Request("GET", "https://api.lemlist.com/api/campaigns", auth=session.auth)
        prepared = request.prepare()
        expected_token = base64.b64encode(b":secret-key").decode("ascii")
        assert prepared.headers["Authorization"] == f"Basic {expected_token}"


# --------------------------------------------------------------------------- #
# source.normalize_campaign
# --------------------------------------------------------------------------- #


class TestNormalizeCampaign:
    def test_renames_id_to_campaign_id(self):
        raw = {"_id": "cam_abc", "name": "x", "status": "running"}
        assert normalize_campaign(raw) == {
            "campaign_id": "cam_abc",
            "name": "x",
            "status": "running",
        }

    def test_preserves_other_fields(self):
        raw = {
            "_id": "cam_abc",
            "name": "Alex - TAC",
            "sequenceId": "seq_1",
            "labels": ["Alex"],
            "errors": ["Your campaign does not have sender."],
            "createdAt": "2025-09-24T19:52:31.424Z",
        }
        result = normalize_campaign(raw)
        assert result["campaign_id"] == "cam_abc"
        assert result["labels"] == ["Alex"]
        assert result["errors"] == ["Your campaign does not have sender."]
        assert result["sequenceId"] == "seq_1"

    # Defensive: server should always send ``_id``, but don't crash if not.
    def test_handles_missing_id(self):
        result = normalize_campaign({"name": "x"})
        assert result["campaign_id"] is None
        assert result["name"] == "x"


# --------------------------------------------------------------------------- #
# source.chunk_ids
# --------------------------------------------------------------------------- #


class TestChunkIds:
    @parameterized.expand(
        [
            ("empty", [], 10, []),
            ("single_chunk_exact", ["a", "b"], 2, [["a", "b"]]),
            ("single_chunk_short", ["a"], 10, [["a"]]),
            ("two_chunks", ["a", "b", "c"], 2, [["a", "b"], ["c"]]),
            (
                "three_chunks",
                ["a", "b", "c", "d", "e", "f", "g"],
                3,
                [["a", "b", "c"], ["d", "e", "f"], ["g"]],
            ),
        ]
    )
    def test_chunks(self, _name, ids, size, expected):
        assert list(chunk_ids(ids, size)) == expected

    @parameterized.expand([("zero", 0), ("negative", -1)])
    def test_invalid_size_raises(self, _name, size):
        with pytest.raises(ValueError):
            list(chunk_ids(["a"], size))


# --------------------------------------------------------------------------- #
# source.build_stats_payload / build_stats_row
# --------------------------------------------------------------------------- #


class TestBuildStatsPayload:
    def test_payload_shape(self):
        payload = build_stats_payload(["cam_a", "cam_b"], date(2018, 1, 1), date(2026, 4, 17))
        assert payload == {
            "campaignIds": ["cam_a", "cam_b"],
            "channels": ["email"],
            "startDate": "2018-01-01T00:00:00.000Z",
            "endDate": "2026-04-17T23:59:59.999Z",
        }


class TestBuildStatsRow:
    def _canned_result(self) -> dict[str, Any]:
        return {
            "campaignId": "cam_123",
            "nbLeads": 32,
            "nbLeadsLaunched": 32,
            "nbLeadsReached": 32,
            "nbLeadsOpened": 31,
            "nbLeadsInteracted": 4,
            "nbLeadsAnswered": 16,
            "nbLeadsInterested": 1,
            "nbLeadsNotInterested": 0,
            "nbLeadsUnsubscribed": 1,
            "nbLeadsInterrupted": 1,
            "messagesSent": 72,
            "messagesNotSent": 0,
            "messagesBounced": 0,
            "delivered": 72,
            "opened": 47,
            "clicked": 4,
            "replied": 16,
            "invitationAccepted": 0,
            "meetingBooked": 0,
            "steps": [
                {
                    "index": 1,
                    "sequenceId": "seq_abc",
                    "sequenceStep": 0,
                    "taskType": "linkedinSend",
                    "invited": 0,
                    "sent": 32,
                    "delivered": 32,
                    "opened": 15,
                    "clicked": 0,
                    "replied": 15,
                    "notDelivered": 0,
                    "bounced": 0,
                    "unsubscribed": 1,
                }
            ],
        }

    def test_renames_campaign_id_and_stamps_snapshot_date(self):
        row = build_stats_row(self._canned_result(), date(2026, 4, 16))
        assert row["campaign_id"] == "cam_123"
        assert row["snapshot_date"] == datetime(2026, 4, 16, tzinfo=UTC)
        assert "campaignId" not in row

    def test_preserves_funnel_counters(self):
        row = build_stats_row(self._canned_result(), date(2026, 4, 16))
        assert row["nbLeads"] == 32
        assert row["nbLeadsOpened"] == 31
        assert row["messagesSent"] == 72
        assert row["meetingBooked"] == 0

    def test_preserves_nested_steps_for_dlt_child_table(self):
        row = build_stats_row(self._canned_result(), date(2026, 4, 16))
        assert isinstance(row["steps"], list)
        assert len(row["steps"]) == 1
        step = row["steps"][0]
        assert step["sequenceId"] == "seq_abc"
        assert step["sequenceStep"] == 0
        assert step["taskType"] == "linkedinSend"
        assert step["sent"] == 32

    def test_input_dict_is_not_mutated(self):
        canned = self._canned_result()
        build_stats_row(canned, date(2026, 4, 16))
        assert canned.get("campaignId") == "cam_123"
        assert "snapshot_date" not in canned


# --------------------------------------------------------------------------- #
# source._iter_campaign_pages
# --------------------------------------------------------------------------- #


class TestIterCampaignPages:
    def _mock_session_with_pages(self, pages: list[dict[str, Any]]) -> MagicMock:
        session = MagicMock(spec=requests.Session)
        session.get.side_effect = [_mock_json_response(p) for p in pages]
        return session

    def test_single_page(self):
        session = self._mock_session_with_pages(
            [
                {
                    "campaigns": [{"_id": "cam_a"}, {"_id": "cam_b"}],
                    "pagination": {"totalRecords": 2, "currentPage": 1, "nextPage": 1, "totalPage": 1},
                }
            ]
        )
        result = list(_iter_campaign_pages(session))
        assert [c["_id"] for c in result] == ["cam_a", "cam_b"]
        assert session.get.call_count == 1

    def test_multi_page_progression(self):
        session = self._mock_session_with_pages(
            [
                {
                    "campaigns": [{"_id": "cam_a"}],
                    "pagination": {"totalRecords": 3, "currentPage": 1, "nextPage": 2, "totalPage": 3},
                },
                {
                    "campaigns": [{"_id": "cam_b"}],
                    "pagination": {"totalRecords": 3, "currentPage": 2, "nextPage": 3, "totalPage": 3},
                },
                {
                    "campaigns": [{"_id": "cam_c"}],
                    "pagination": {"totalRecords": 3, "currentPage": 3, "nextPage": 3, "totalPage": 3},
                },
            ]
        )
        result = list(_iter_campaign_pages(session))
        assert [c["_id"] for c in result] == ["cam_a", "cam_b", "cam_c"]
        assert session.get.call_count == 3

    def test_stops_when_next_page_does_not_advance(self):
        session = self._mock_session_with_pages(
            [
                {
                    "campaigns": [{"_id": "cam_a"}],
                    "pagination": {"currentPage": 1, "nextPage": 1, "totalPage": 2},
                }
            ]
        )
        result = list(_iter_campaign_pages(session))
        assert [c["_id"] for c in result] == ["cam_a"]
        assert session.get.call_count == 1

    def test_empty_body_stops(self):
        session = self._mock_session_with_pages([{}])
        assert list(_iter_campaign_pages(session)) == []
        assert session.get.call_count == 1

    def test_missing_pagination_stops_after_first_page(self):
        session = self._mock_session_with_pages([{"campaigns": [{"_id": "cam_a"}, {"_id": "cam_b"}]}])
        result = list(_iter_campaign_pages(session))
        assert [c["_id"] for c in result] == ["cam_a", "cam_b"]
        assert session.get.call_count == 1


# --------------------------------------------------------------------------- #
# source._fetch_stats_batch
# --------------------------------------------------------------------------- #


class TestFetchStatsBatch:
    def test_posts_expected_payload_and_returns_results(self):
        session = MagicMock(spec=requests.Session)
        session.post.return_value = _mock_json_response(
            {"results": [{"campaignId": "cam_a", "nbLeads": 1}], "errors": []}
        )
        results = _fetch_stats_batch(session, ["cam_a", "cam_b"], date(2018, 1, 1), date(2026, 4, 17))

        assert results == [{"campaignId": "cam_a", "nbLeads": 1}]
        session.post.assert_called_once()
        posted_json = session.post.call_args.kwargs["json"]
        assert posted_json == {
            "campaignIds": ["cam_a", "cam_b"],
            "channels": ["email"],
            "startDate": "2018-01-01T00:00:00.000Z",
            "endDate": "2026-04-17T23:59:59.999Z",
        }

    def test_missing_results_returns_empty_list(self):
        session = MagicMock(spec=requests.Session)
        session.post.return_value = _mock_json_response({"errors": []})
        assert _fetch_stats_batch(session, ["cam_a"], date(2018, 1, 1), date(2026, 4, 17)) == []


# --------------------------------------------------------------------------- #
# destination.build_pipeline
# --------------------------------------------------------------------------- #


class TestBuildPipeline:
    @override_settings(DUCKGRES_PG_URL=None)
    def test_missing_duckgres_url_raises(self):
        with pytest.raises(DuckgresNotConfiguredError):
            build_pipeline()


# --------------------------------------------------------------------------- #
# lemlist_source — end-to-end against an ephemeral DuckDB destination.
#
# This exercises the full campaigns + campaign_stats_daily +
# campaign_stats_daily__steps graph through a real dlt pipeline so future
# refactors that desynchronize the two resources' pagination or row shapes
# surface as a test failure rather than a silent production divergence.
# --------------------------------------------------------------------------- #


def _stub_session(get_responses: list[MagicMock], post_responses: list[MagicMock]) -> MagicMock:
    session = MagicMock(spec=requests.Session)
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    session.get = MagicMock(side_effect=get_responses)
    session.post = MagicMock(side_effect=post_responses)
    return session


@pytest.fixture
def lemlist_snake_case_naming(monkeypatch):
    """Pin snake_case naming on the lemlist source regardless of process state.

    ``posthog/temporal/data_modeling/run_workflow.py`` may set
    ``SCHEMA__NAMING=direct`` at import time. Empirically, dlt 1.18 resolves
    the schema's naming convention from that env var before consulting the
    per-source ``dlt.config`` key, so we have to override the env directly.
    ``monkeypatch.setenv`` restores the prior value on teardown.
    """
    monkeypatch.setenv("SCHEMA__NAMING", "snake_case")


class TestLemlistSourceIntegration:
    def test_end_to_end_materializes_campaigns_stats_and_steps(self, tmp_path, lemlist_snake_case_naming):
        campaigns_page = {
            "campaigns": [
                {"_id": "cam_a", "name": "A", "status": "running"},
                {"_id": "cam_b", "name": "B", "status": "paused"},
            ],
            "pagination": {"currentPage": 1, "nextPage": 1, "totalPage": 1},
        }
        stats_response = {
            "results": [
                {
                    "campaignId": "cam_a",
                    "nbLeads": 10,
                    "messagesSent": 20,
                    "steps": [
                        {"index": 1, "sequenceStep": 0, "taskType": "email", "sent": 20},
                    ],
                },
                {
                    "campaignId": "cam_b",
                    "nbLeads": 5,
                    "messagesSent": 10,
                    "steps": [],
                },
            ],
            "errors": [],
        }

        def session_factory():
            return _stub_session(
                get_responses=[_mock_json_response(campaigns_page)],
                post_responses=[_mock_json_response(stats_response)],
            )

        pipeline = dlt.pipeline(
            pipeline_name="lemlist_e2e_test",
            destination=dlt.destinations.duckdb(str(tmp_path / "lemlist.duckdb")),
            dataset_name="lemlist_e2e",
        )
        info = pipeline.run(lemlist_source(session_factory=session_factory, snapshot_date=date(2026, 4, 17)))
        assert not info.has_failed_jobs

        with pipeline.sql_client() as client:
            with client.execute_query("SELECT campaign_id FROM campaigns ORDER BY campaign_id") as cursor:
                campaigns_rows = [row[0] for row in cursor.fetchall()]
            with client.execute_query("SELECT campaign_id FROM campaign_stats_daily ORDER BY campaign_id") as cursor:
                stats_rows = [row[0] for row in cursor.fetchall()]
            with client.execute_query("SELECT task_type, sent FROM campaign_stats_daily__steps") as cursor:
                steps_rows = cursor.fetchall()

        assert campaigns_rows == ["cam_a", "cam_b"]
        assert stats_rows == ["cam_a", "cam_b"]
        assert steps_rows == [("email", 20)]


# --------------------------------------------------------------------------- #
# lemlist_campaigns_and_stats asset — failure paths.
# --------------------------------------------------------------------------- #


class TestLemlistAssetFailures:
    def test_empty_api_key_surfaces_as_asset_failure(self, tmp_path, monkeypatch, lemlist_snake_case_naming):
        stub_pipeline = dlt.pipeline(
            pipeline_name="lemlist_failure_test",
            destination=dlt.destinations.duckdb(str(tmp_path / "lemlist_failure.duckdb")),
            dataset_name="lemlist_failure",
        )
        monkeypatch.setattr(lemlist_dag, "build_pipeline", lambda: stub_pipeline)

        result = dagster.materialize(
            [lemlist_campaigns_and_stats],
            resources={"lemlist_auth": LemlistAuthResource(api_key="")},
            run_config={
                "ops": {
                    "lemlist_campaigns_and_stats": {
                        "config": {"snapshot_date": "2026-04-17"},
                    }
                }
            },
            raise_on_error=False,
        )
        assert not result.success
        step_failures = [event for event in result.all_events if event.event_type_value == "STEP_FAILURE"]
        assert step_failures, "expected a STEP_FAILURE event"
        failure_message = str(step_failures[0])
        assert "Lemlist API key" in failure_message


# --------------------------------------------------------------------------- #
# lemlist_daily_schedule — tick-to-RunRequest mapping.
# --------------------------------------------------------------------------- #


class TestLemlistDailySchedule:
    def test_scheduled_tick_sets_run_key_and_snapshot_date(self):
        tick_time = datetime(2026, 4, 17, 6, 0, tzinfo=UTC)
        context = dagster.build_schedule_context(scheduled_execution_time=tick_time)
        run_request = lemlist_dag.lemlist_daily_schedule(context)
        assert isinstance(run_request, dagster.RunRequest)
        assert run_request.run_key == "2026-04-17"
        assert run_request.run_config == {
            "ops": {
                "lemlist_campaigns_and_stats": {"config": {"snapshot_date": "2026-04-17"}},
            }
        }

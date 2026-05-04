from typing import Any

import pytest
from unittest import mock

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.instagram.instagram import (
    InstagramResumeConfig,
    _flatten_insights,
    _iter_fanout_insights,
    _iter_simple_cursor,
    _strip_access_token,
)
from posthog.temporal.data_imports.sources.instagram.schemas import (
    INCREMENTAL_FIELDS,
    RESOURCE_SCHEMAS,
    InstagramResource,
)


def _mock_response(status: int, body: dict) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status
    response.json.return_value = body
    response.text = ""
    return response


def _build_manager(*, can_resume: bool = False, state: InstagramResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestStripAccessToken:
    @pytest.mark.parametrize(
        "url,expected",
        [
            (
                "https://graph.facebook.com/v23.0/next?access_token=secret&cursor=abc",
                "https://graph.facebook.com/v23.0/next?cursor=abc",
            ),
            (
                "https://graph.facebook.com/v23.0/next?cursor=abc&access_token=secret",
                "https://graph.facebook.com/v23.0/next?cursor=abc",
            ),
            (
                "https://graph.facebook.com/v23.0/next?access_token=secret",
                "https://graph.facebook.com/v23.0/next",
            ),
            (
                "https://graph.facebook.com/v23.0/next?cursor=abc",
                "https://graph.facebook.com/v23.0/next?cursor=abc",
            ),
            (
                "https://graph.facebook.com/v23.0/next",
                "https://graph.facebook.com/v23.0/next",
            ),
            (
                "https://example/path?access_token=a&foo=1&access_token=b",
                "https://example/path?foo=1",
            ),
        ],
    )
    def test_strips(self, url: str, expected: str) -> None:
        assert _strip_access_token(url) == expected


class TestFlattenInsights:
    def test_flattens_one_metric_one_value(self):
        rows = _flatten_insights(
            [
                {
                    "name": "impressions",
                    "period": "day",
                    "title": "Impressions",
                    "description": "Total impressions",
                    "values": [{"value": 42, "end_time": "2026-04-01T07:00:00+0000"}],
                }
            ],
            parent_id="ig_123",
            parent_id_key="ig_user_id",
            parent_timestamp=None,
        )
        assert rows == [
            {
                "ig_user_id": "ig_123",
                "name": "impressions",
                "period": "day",
                "title": "Impressions",
                "description": "Total impressions",
                "value": 42,
                "end_time": "2026-04-01T07:00:00+0000",
            }
        ]

    def test_attaches_parent_timestamp_when_provided(self):
        rows = _flatten_insights(
            [{"name": "reach", "period": "lifetime", "values": [{"value": 100}]}],
            parent_id="m1",
            parent_id_key="media_id",
            parent_timestamp="2026-01-01T00:00:00+0000",
        )
        assert len(rows) == 1
        assert rows[0]["media_id"] == "m1"
        assert rows[0]["timestamp"] == "2026-01-01T00:00:00+0000"

    def test_one_metric_many_values(self):
        rows = _flatten_insights(
            [
                {
                    "name": "impressions",
                    "values": [
                        {"value": 1, "end_time": "2026-04-01T00:00:00+0000"},
                        {"value": 2, "end_time": "2026-04-02T00:00:00+0000"},
                    ],
                }
            ],
            parent_id="x",
            parent_id_key="ig_user_id",
            parent_timestamp=None,
        )
        assert len(rows) == 2
        assert rows[0]["value"] == 1
        assert rows[1]["value"] == 2


class TestSimpleCursorPagination:
    INITIAL_URL = "https://graph.facebook.com/v23.0/ig_123/media"
    INITIAL_PARAMS: dict[str, Any] = {"fields": "id,timestamp", "limit": 100}

    def test_fresh_run_follows_paging_next(self):
        manager = _build_manager()
        responses = [
            _mock_response(
                200,
                {
                    "data": [{"id": "1"}, {"id": "2"}],
                    "paging": {"next": "https://graph.facebook.com/v23.0/next?access_token=tok&cursor=abc"},
                },
            ),
            _mock_response(200, {"data": [{"id": "3"}], "paging": {}}),
        ]

        with mock.patch(
            "posthog.temporal.data_imports.sources.instagram.instagram.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.side_effect = responses
            batches = list(
                _iter_simple_cursor(
                    self.INITIAL_URL,
                    self.INITIAL_PARAMS,
                    "tok",
                    None,
                    manager,
                )
            )

        assert batches == [[{"id": "1"}, {"id": "2"}], [{"id": "3"}]]
        # State should have been saved exactly once — after the first batch, with
        # the access_token-stripped next URL.
        assert manager.save_state.call_count == 1
        saved = manager.save_state.call_args.args[0]
        assert isinstance(saved, InstagramResumeConfig)
        assert saved.next_url == "https://graph.facebook.com/v23.0/next?cursor=abc"

    def test_resume_skips_initial_request(self):
        manager = _build_manager(
            can_resume=True,
            state=InstagramResumeConfig(next_url="https://graph.facebook.com/v23.0/next?cursor=abc"),
        )
        response = _mock_response(200, {"data": [{"id": "9"}], "paging": {}})

        with mock.patch(
            "posthog.temporal.data_imports.sources.instagram.instagram.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.return_value = response
            batches = list(
                _iter_simple_cursor(
                    self.INITIAL_URL,
                    self.INITIAL_PARAMS,
                    "tok",
                    manager.load_state(),
                    manager,
                )
            )

        assert batches == [[{"id": "9"}]]
        # The first (and only) GET should have been to the saved URL, not the initial URL.
        first_call = mock_session.return_value.get.call_args_list[0]
        assert first_call.args[0] == "https://graph.facebook.com/v23.0/next?cursor=abc"

    def test_non_200_raises(self):
        manager = _build_manager()
        with mock.patch(
            "posthog.temporal.data_imports.sources.instagram.instagram.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.return_value = _mock_response(401, {"error": "bad token"})
            with pytest.raises(Exception, match="Instagram API request failed"):
                list(
                    _iter_simple_cursor(
                        self.INITIAL_URL,
                        self.INITIAL_PARAMS,
                        "tok",
                        None,
                        manager,
                    )
                )


class TestFanoutInsights:
    PARENT_URL = "https://graph.facebook.com/v23.0/ig_123/media"

    def test_fans_out_per_parent_and_skips_400(self):
        manager = _build_manager()

        # Parent page returns two media rows; second media's insights endpoint
        # returns 400 (e.g. metric not supported for that media type) and should
        # be silently skipped, not crash the sync.
        parent_response = _mock_response(
            200,
            {
                "data": [
                    {"id": "m1", "timestamp": "2026-04-01T00:00:00+0000"},
                    {"id": "m2", "timestamp": "2026-04-02T00:00:00+0000"},
                ],
                "paging": {},
            },
        )
        m1_insights = _mock_response(
            200,
            {"data": [{"name": "impressions", "values": [{"value": 5}]}]},
        )
        m2_insights_400 = _mock_response(400, {"error": "(#100) metric not supported"})

        with mock.patch(
            "posthog.temporal.data_imports.sources.instagram.instagram.make_tracked_session"
        ) as mock_session:
            mock_session.return_value.get.side_effect = [parent_response, m1_insights, m2_insights_400]
            batches = list(
                _iter_fanout_insights(
                    parent_url=self.PARENT_URL,
                    parent_fields=["id", "timestamp"],
                    metrics=["impressions"],
                    parent_id_key="media_id",
                    access_token="tok",
                    resume_config=None,
                    resumable_source_manager=manager,
                )
            )

        assert len(batches) == 1
        rows = batches[0]
        assert len(rows) == 1
        assert rows[0]["media_id"] == "m1"
        assert rows[0]["timestamp"] == "2026-04-01T00:00:00+0000"
        assert rows[0]["name"] == "impressions"


class TestSchemaCatalog:
    def test_all_endpoints_have_required_fields(self):
        for _resource, schema in RESOURCE_SCHEMAS.items():
            assert "primary_keys" in schema
            assert isinstance(schema["primary_keys"], list)
            assert len(schema["primary_keys"]) >= 1
            assert "url" in schema
            assert schema["url"].startswith("https://graph.facebook.com/")
            assert "kind" in schema

    @pytest.mark.parametrize(
        "resource,expected_pk",
        [
            (InstagramResource.Users, ["id"]),
            (InstagramResource.Media, ["id"]),
            (InstagramResource.Stories, ["id"]),
            (InstagramResource.MediaInsights, ["media_id", "name"]),
            (InstagramResource.StoryInsights, ["story_id", "name"]),
            (InstagramResource.UserInsights, ["ig_user_id", "name", "end_time"]),
        ],
    )
    def test_primary_key_for_each_endpoint(self, resource: InstagramResource, expected_pk: list[str]):
        assert RESOURCE_SCHEMAS[resource]["primary_keys"] == expected_pk

    def test_only_user_insights_is_in_incremental_fields(self):
        assert set(INCREMENTAL_FIELDS.keys()) == {InstagramResource.UserInsights}

    def test_partition_keys_use_stable_fields(self):
        # Picking a stable partition key (timestamp/end_time) is critical — using
        # an updated_at would cause partition rewrites on every sync.
        for resource, schema in RESOURCE_SCHEMAS.items():
            for key in schema.get("partition_keys") or []:
                assert key in {"timestamp", "end_time"}, f"{resource}: unstable partition key {key}"

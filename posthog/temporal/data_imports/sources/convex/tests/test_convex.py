from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, Mock, patch

from parameterized import parameterized

from posthog.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from posthog.temporal.data_imports.sources.convex.convex import (
    ConvexResumeConfig,
    InvalidDeployUrlError,
    convex_source,
    document_deltas,
    list_snapshot,
    validate_credentials,
    validate_deploy_url,
)


def _make_response(json_data: dict[str, Any], status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    response.raise_for_status = Mock()
    return response


def _make_manager(can_resume: bool = False, state: ConvexResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestValidateDeployUrl:
    @parameterized.expand(
        [
            # valid — should normalize to clean https://host
            ("simple", "https://swift-lemur-123.convex.cloud", "https://swift-lemur-123.convex.cloud"),
            ("trailing_slash", "https://swift-lemur-123.convex.cloud/", "https://swift-lemur-123.convex.cloud"),
            ("uppercase", "HTTPS://Swift-Lemur-123.CONVEX.CLOUD", "https://swift-lemur-123.convex.cloud"),
            ("leading_space", "  https://swift-lemur-123.convex.cloud", "https://swift-lemur-123.convex.cloud"),
            ("with_path", "https://swift-lemur-123.convex.cloud/some/path", "https://swift-lemur-123.convex.cloud"),
            # invalid — should raise
            ("http", "http://swift-lemur-123.convex.cloud", None),
            ("ftp", "ftp://swift-lemur-123.convex.cloud", None),
            ("no_scheme", "swift-lemur-123.convex.cloud", None),
            ("wrong_tld", "https://swift-lemur-123.convex.io", None),
            ("extra_subdomain", "https://extra.swift-lemur-123.convex.cloud", None),
            ("lookalike", "https://convex.cloud.evil.com", None),
            ("bare_domain", "https://convex.cloud", None),
            ("ip_literal", "https://1.2.3.4", None),
            ("localhost", "https://localhost", None),
            ("metadata_ip", "https://169.254.169.254", None),
            ("internal_domain", "https://swift-lemur-123.convex.cloud.internal", None),
            ("query_params", "https://swift-lemur-123.convex.cloud?evil=1", None),
            ("fragment", "https://swift-lemur-123.convex.cloud#section", None),
        ]
    )
    def test_validate_deploy_url(self, _name, url, expected):
        if expected is not None:
            assert validate_deploy_url(url) == expected
        else:
            with pytest.raises(InvalidDeployUrlError):
                validate_deploy_url(url)

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_validate_credentials_rejects_bad_url_without_network_call(self, mock_get):
        ok, err = validate_credentials("http://169.254.169.254", "deploy-key")
        assert not ok
        assert err is not None
        mock_get.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_validate_credentials_accepts_valid_url(self, mock_get):
        mock_response = Mock(status_code=200)
        mock_response.json.return_value = {}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        ok, err = validate_credentials("https://swift-lemur-123.convex.cloud", "prod:abc123")
        assert ok
        assert err is None
        called_url = mock_get.call_args.args[0]
        assert called_url.startswith("https://swift-lemur-123.convex.cloud/api/")


class TestListSnapshotResumable:
    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_fresh_run_saves_state_after_each_page(self, mock_get: Mock) -> None:
        manager = _make_manager(can_resume=False)
        mock_get.side_effect = [
            _make_response({"values": [{"_id": "a"}], "cursor": 100, "snapshot": 500, "hasMore": True}),
            _make_response({"values": [{"_id": "b"}], "cursor": 200, "snapshot": 500, "hasMore": True}),
            _make_response({"values": [{"_id": "c"}], "cursor": 300, "snapshot": 500, "hasMore": False}),
        ]

        gen = list_snapshot("https://x.convex.cloud", "key", "t", manager)
        batches = list(gen)

        assert batches == [[{"_id": "a"}], [{"_id": "b"}], [{"_id": "c"}]]
        manager.can_resume.assert_called_once()
        manager.load_state.assert_not_called()

        # State saved after each non-terminal page points to the NEXT page's cursor/snapshot.
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [
            ConvexResumeConfig(cursor=100, snapshot=500),
            ConvexResumeConfig(cursor=200, snapshot=500),
        ]

        # First request has no cursor/snapshot params; subsequent requests use the saved values.
        first_params = mock_get.call_args_list[0].kwargs["params"]
        assert "cursor" not in first_params
        assert "snapshot" not in first_params
        second_params = mock_get.call_args_list[1].kwargs["params"]
        assert second_params["cursor"] == 100
        assert second_params["snapshot"] == 500

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_resume_seeds_paginator_from_saved_state(self, mock_get: Mock) -> None:
        saved = ConvexResumeConfig(cursor=200, snapshot=500)
        manager = _make_manager(can_resume=True, state=saved)
        mock_get.return_value = _make_response(
            {"values": [{"_id": "b"}], "cursor": 300, "snapshot": 500, "hasMore": False}
        )

        batches = list(list_snapshot("https://x.convex.cloud", "key", "t", manager))

        assert batches == [[{"_id": "b"}]]
        manager.load_state.assert_called_once()
        # Paginator must start from saved cursor/snapshot, not from scratch.
        first_params = mock_get.call_args_list[0].kwargs["params"]
        assert first_params["cursor"] == 200
        assert first_params["snapshot"] == 500
        # Final page terminates the loop before any save_state.
        manager.save_state.assert_not_called()

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_empty_final_page_does_not_save_state(self, mock_get: Mock) -> None:
        manager = _make_manager(can_resume=False)
        mock_get.return_value = _make_response({"values": [], "snapshot": 0, "hasMore": False})

        batches = list(list_snapshot("https://x.convex.cloud", "key", "t", manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestDocumentDeltasResumable:
    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_fresh_run_saves_state_after_each_page(self, mock_get: Mock) -> None:
        manager = _make_manager(can_resume=False)
        mock_get.side_effect = [
            _make_response({"values": [{"_id": "a"}], "cursor": 20, "hasMore": True}),
            _make_response({"values": [{"_id": "b"}], "cursor": 30, "hasMore": False}),
        ]

        batches = list(document_deltas("https://x.convex.cloud", "key", "t", 10, manager))

        assert batches == [[{"_id": "a"}], [{"_id": "b"}]]
        manager.can_resume.assert_called_once()
        manager.load_state.assert_not_called()
        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ConvexResumeConfig(cursor=20)]

        # First request starts from the provided db cursor.
        first_params = mock_get.call_args_list[0].kwargs["params"]
        assert first_params["cursor"] == 10

    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_resume_overrides_db_cursor(self, mock_get: Mock) -> None:
        saved = ConvexResumeConfig(cursor=25)
        manager = _make_manager(can_resume=True, state=saved)
        mock_get.return_value = _make_response({"values": [{"_id": "b"}], "cursor": 30, "hasMore": False})

        batches = list(document_deltas("https://x.convex.cloud", "key", "t", 10, manager))

        assert batches == [[{"_id": "b"}]]
        # Resume state wins over the db_incremental_field_last_value seed.
        first_params = mock_get.call_args_list[0].kwargs["params"]
        assert first_params["cursor"] == 25
        manager.save_state.assert_not_called()


class TestConvexSource:
    @parameterized.expand(
        [
            (
                "full_refresh",
                False,
                None,
                {"values": [{"_id": "a", "_creationTime": 1}], "cursor": 100, "snapshot": 500, "hasMore": False},
                [[{"_id": "a", "_creationTime": 1}]],
                "/api/list_snapshot",
                {},
            ),
            (
                "incremental",
                True,
                10,
                {"values": [{"_id": "a"}], "cursor": 50, "hasMore": False},
                [[{"_id": "a"}]],
                "/api/document_deltas",
                {"cursor": 10},
            ),
        ]
    )
    @patch("posthog.temporal.data_imports.sources.convex.convex.requests.get")
    def test_threads_manager(
        self,
        _name: str,
        should_use_incremental_field: bool,
        db_incremental_field_last_value: int | None,
        response_json: dict[str, Any],
        expected_batches: list[list[dict[str, Any]]],
        expected_url_fragment: str,
        expected_first_params: dict[str, Any],
        mock_get: Mock,
    ) -> None:
        manager = _make_manager(can_resume=False)
        mock_get.return_value = _make_response(response_json)

        response = convex_source(
            deploy_url="https://x.convex.cloud",
            deploy_key="key",
            table_name="t",
            team_id=1,
            job_id="job",
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            resumable_source_manager=manager,
        )

        batches = list(cast(Iterable[Any], response.items()))
        assert batches == expected_batches
        assert response.primary_keys == ["_id"]
        manager.can_resume.assert_called_once()
        called_url = mock_get.call_args_list[0].args[0]
        assert expected_url_fragment in called_url
        first_params = mock_get.call_args_list[0].kwargs["params"]
        for key, value in expected_first_params.items():
            assert first_params[key] == value

from datetime import UTC, datetime
from typing import Any

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.api.capture_dispatch import (
    CAPTURE_INTERNAL_ROUTED,
    CAPTURE_ROUTED_ERROR,
    CaptureRoutedError,
    RoutedCaptureResult,
    _capture_v1_enabled,
    capture_batch_internal_routed,
    capture_internal_routed,
)


def _make_team(pk: int = 1, organization_id: str = "org-1", api_token: str = "phc_test") -> MagicMock:
    team = MagicMock()
    team.pk = pk
    team.id = pk
    team.organization_id = organization_id
    team.api_token = api_token
    return team


def _make_ok_result(status_code: int = 200) -> MagicMock:
    result = MagicMock()
    result.status_code = status_code
    result.raise_for_status.return_value = None
    return result


COMMON_KWARGS: dict[str, Any] = {
    "token": "phc_test",
    "event_name": "test_event",
    "distinct_id": "user-1",
    "timestamp": datetime.now(UTC),
    "properties": {"key": "value"},
    "event_source": "person_viewset",
}


class TestRoutedCaptureResult(SimpleTestCase):
    def test_success_no_raise(self) -> None:
        r = RoutedCaptureResult(status_code=200, impl="legacy")
        r.raise_for_status()

    def test_error_raises_with_status(self) -> None:
        r = RoutedCaptureResult(status_code=503, impl="legacy", error_message="server error")
        with self.assertRaises(CaptureRoutedError) as ctx:
            r.raise_for_status()
        assert ctx.exception.status_code == 503
        assert "server error" in str(ctx.exception)


class TestCaptureRoutedError(SimpleTestCase):
    def test_is_subclass_of_capture_internal_error(self) -> None:
        from posthog.api.capture import CaptureInternalError

        err = CaptureRoutedError("test", status_code=404)
        assert isinstance(err, CaptureInternalError)
        assert err.status_code == 404


class TestCaptureV1Enabled(SimpleTestCase):
    def test_unknown_event_source_returns_false(self) -> None:
        team = _make_team()
        assert _capture_v1_enabled("nonexistent_source", team=team) is False

    def test_no_team_and_no_token_returns_false(self) -> None:
        assert _capture_v1_enabled("person_viewset") is False

    @patch("posthog.api.capture_dispatch.posthoganalytics.feature_enabled", return_value=True)
    def test_flag_enabled_returns_true(self, mock_flag: MagicMock) -> None:
        team = _make_team()
        assert _capture_v1_enabled("person_viewset", team=team) is True
        mock_flag.assert_called_once()
        call_kwargs = mock_flag.call_args.kwargs
        assert call_kwargs["only_evaluate_locally"] is True
        assert call_kwargs["send_feature_flag_events"] is False

    @patch("posthog.api.capture_dispatch.posthoganalytics.feature_enabled", return_value=False)
    def test_flag_disabled_returns_false(self, mock_flag: MagicMock) -> None:
        team = _make_team()
        assert _capture_v1_enabled("person_viewset", team=team) is False

    @patch("posthog.api.capture_dispatch.posthoganalytics.feature_enabled", side_effect=Exception("boom"))
    def test_exception_returns_false(self, mock_flag: MagicMock) -> None:
        team = _make_team()
        assert _capture_v1_enabled("person_viewset", team=team) is False

    @patch("posthog.api.capture_dispatch.posthoganalytics.feature_enabled", return_value=None)
    def test_none_returns_false(self, mock_flag: MagicMock) -> None:
        team = _make_team()
        assert _capture_v1_enabled("person_viewset", team=team) is False

    @patch("posthog.api.capture_dispatch.posthoganalytics.feature_enabled", return_value=True)
    def test_token_resolves_team(self, mock_flag: MagicMock) -> None:
        team = _make_team()
        with patch(
            "posthog.models.team.team.TeamManager.get_team_from_cache_or_token", return_value=team
        ) as mock_resolve:
            result = _capture_v1_enabled("person_viewset", token="phc_test")
            assert result is True
            mock_resolve.assert_called_once_with("phc_test")


class TestCaptureInternalRouted(SimpleTestCase):
    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=False)
    @patch("posthog.api.capture_dispatch.capture_internal")
    def test_flag_off_routes_to_legacy(self, mock_capture: MagicMock, mock_flag: MagicMock) -> None:
        mock_capture.return_value = _make_ok_result()
        team = _make_team()

        result = capture_internal_routed(**COMMON_KWARGS, team=team)
        assert result.impl == "legacy"
        assert result.status_code == 200
        result.raise_for_status()
        mock_capture.assert_called_once()

    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=True)
    @patch("posthog.api.capture_dispatch.capture_v1_internal")
    def test_flag_on_routes_to_v1(self, mock_v1: MagicMock, mock_flag: MagicMock) -> None:
        mock_v1.return_value = _make_ok_result()
        team = _make_team()

        result = capture_internal_routed(**COMMON_KWARGS, team=team)
        assert result.impl == "v1"
        assert result.status_code == 200
        result.raise_for_status()
        mock_v1.assert_called_once()

    @parameterized.expand([("$snapshot",), ("$performance_event",), ("$snapshot_items",)])
    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=True)
    @patch("posthog.api.capture_dispatch.capture_internal")
    def test_all_replay_event_names_force_legacy(
        self, event_name: str, mock_capture: MagicMock, mock_flag: MagicMock
    ) -> None:
        mock_capture.return_value = _make_ok_result()
        kwargs = {**COMMON_KWARGS, "event_name": event_name}
        result = capture_internal_routed(**kwargs, team=_make_team())
        assert result.impl == "legacy"

    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=False)
    @patch("posthog.api.capture_dispatch.capture_internal")
    def test_legacy_http_error_normalized(self, mock_capture: MagicMock, mock_flag: MagicMock) -> None:
        from requests import HTTPError

        resp_mock = MagicMock()
        resp_mock.status_code = 503
        resp_mock.raise_for_status.side_effect = HTTPError(response=resp_mock)
        mock_capture.return_value = resp_mock

        result = capture_internal_routed(**COMMON_KWARGS, team=_make_team())
        assert result.impl == "legacy"
        assert result.status_code == 503
        with self.assertRaises(CaptureRoutedError) as ctx:
            result.raise_for_status()
        assert ctx.exception.status_code == 503

    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=True)
    @patch("posthog.api.capture_dispatch.capture_v1_internal")
    def test_v1_error_normalized(self, mock_v1: MagicMock, mock_flag: MagicMock) -> None:
        from posthog.api.capture_v1 import CaptureV1InternalError

        v1_result = MagicMock()
        v1_result.status_code = 200
        v1_result.raise_for_status.side_effect = CaptureV1InternalError("partial failure")
        mock_v1.return_value = v1_result

        result = capture_internal_routed(**COMMON_KWARGS, team=_make_team())
        assert result.impl == "v1"
        with self.assertRaises(CaptureRoutedError):
            result.raise_for_status()

    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=False)
    @patch("posthog.api.capture_dispatch.capture_internal", side_effect=ConnectionError("refused"))
    def test_legacy_transport_error_normalized(self, mock_capture: MagicMock, mock_flag: MagicMock) -> None:
        result = capture_internal_routed(**COMMON_KWARGS, team=_make_team())
        assert result.impl == "legacy"
        assert result.status_code == 0
        with self.assertRaises(CaptureRoutedError):
            result.raise_for_status()

    def test_routing_metric_incremented(self) -> None:
        before_legacy = CAPTURE_INTERNAL_ROUTED.labels(event_source="person_viewset", impl="legacy")._value.get()
        with (
            patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=False),
            patch("posthog.api.capture_dispatch.capture_internal", return_value=_make_ok_result()),
        ):
            capture_internal_routed(**COMMON_KWARGS, team=_make_team())
        after_legacy = CAPTURE_INTERNAL_ROUTED.labels(event_source="person_viewset", impl="legacy")._value.get()
        assert after_legacy == before_legacy + 1

    def test_error_metric_incremented_on_failure(self) -> None:
        from requests import HTTPError

        before = CAPTURE_ROUTED_ERROR.labels(
            event_source="person_viewset", impl="legacy", error_type="http"
        )._value.get()
        resp_mock = MagicMock()
        resp_mock.status_code = 500
        resp_mock.raise_for_status.side_effect = HTTPError(response=resp_mock)
        with (
            patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=False),
            patch("posthog.api.capture_dispatch.capture_internal", return_value=resp_mock),
        ):
            capture_internal_routed(**COMMON_KWARGS, team=_make_team())
        after = CAPTURE_ROUTED_ERROR.labels(
            event_source="person_viewset", impl="legacy", error_type="http"
        )._value.get()
        assert after == before + 1

    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=False)
    @patch("posthog.api.capture_dispatch.capture_internal")
    def test_capture_internal_error_propagates_directly(self, mock_capture: MagicMock, mock_flag: MagicMock) -> None:
        from posthog.api.capture import CaptureInternalError

        mock_capture.side_effect = CaptureInternalError("bad token")
        with self.assertRaises(CaptureInternalError):
            capture_internal_routed(**COMMON_KWARGS, team=_make_team())


class TestCaptureBatchInternalRouted(SimpleTestCase):
    BATCH_KWARGS: dict[str, Any] = {
        "events": [{"event": "e1", "distinct_id": "u1", "properties": {}}],
        "event_source": "get_csp_report",
        "token": "phc_test",
    }

    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=False)
    @patch("posthog.api.capture_dispatch.capture_batch_internal")
    def test_flag_off_routes_to_legacy_batch(self, mock_batch: MagicMock, mock_flag: MagicMock) -> None:
        future = MagicMock()
        future.result.return_value = _make_ok_result()
        mock_batch.return_value = [future]

        result = capture_batch_internal_routed(**self.BATCH_KWARGS)
        assert result.impl == "legacy"
        result.raise_for_status()

    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=True)
    @patch("posthog.api.capture_dispatch.capture_v1_batch_internal")
    def test_flag_on_routes_to_v1_batch(self, mock_v1: MagicMock, mock_flag: MagicMock) -> None:
        mock_v1.return_value = _make_ok_result()

        result = capture_batch_internal_routed(**self.BATCH_KWARGS)
        assert result.impl == "v1"
        result.raise_for_status()

    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=False)
    @patch("posthog.api.capture_dispatch.capture_batch_internal")
    def test_legacy_batch_http_error(self, mock_batch: MagicMock, mock_flag: MagicMock) -> None:
        from requests import HTTPError

        resp_mock = MagicMock()
        resp_mock.status_code = 500
        resp_mock.raise_for_status.side_effect = HTTPError(response=resp_mock)
        future = MagicMock()
        future.result.return_value = resp_mock
        mock_batch.return_value = [future]

        result = capture_batch_internal_routed(**self.BATCH_KWARGS)
        assert result.status_code == 500
        with self.assertRaises(CaptureRoutedError):
            result.raise_for_status()

    @patch("posthog.api.capture_dispatch._capture_v1_enabled", return_value=True)
    @patch("posthog.api.capture_dispatch.capture_v1_batch_internal")
    def test_v1_batch_error(self, mock_v1: MagicMock, mock_flag: MagicMock) -> None:
        from posthog.api.capture_v1 import CaptureV1InternalError

        v1_result = MagicMock()
        v1_result.raise_for_status.side_effect = CaptureV1InternalError("dropped")
        mock_v1.return_value = v1_result

        result = capture_batch_internal_routed(**self.BATCH_KWARGS)
        assert result.impl == "v1"
        with self.assertRaises(CaptureRoutedError):
            result.raise_for_status()

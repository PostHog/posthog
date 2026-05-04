from datetime import UTC, datetime, timedelta, timezone

from unittest import mock

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType

from posthog.temporal.data_imports.sources.generated_configs import PostmarkSourceConfig
from posthog.temporal.data_imports.sources.postmark.postmark import (
    POSTMARK_BASE_URL,
    PostmarkRetryableError,
    _build_params,
    _format_postmark_datetime,
    _get_headers,
    _resolve_fromdate,
    get_rows,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.postmark.settings import (
    ENDPOINTS,
    POSTMARK_ENDPOINTS,
    POSTMARK_OUTBOUND_MAX_WINDOW_DAYS,
    POSTMARK_PAGE_SIZE,
)
from posthog.temporal.data_imports.sources.postmark.source import PostmarkSource

from products.data_warehouse.backend.types import ExternalDataSourceType


class TestFormatPostmarkDatetime:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            (
                "non_utc_converted",
                datetime(2026, 3, 4, 12, 58, 14, tzinfo=timezone(timedelta(hours=10))),
                "2026-03-04T02:58:14",
            ),
        ]
    )
    def test_format(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_postmark_datetime(value) == expected

    def test_no_offset_suffix(self) -> None:
        assert "+" not in _format_postmark_datetime(datetime(2026, 3, 4, tzinfo=UTC))
        assert "Z" not in _format_postmark_datetime(datetime(2026, 3, 4, tzinfo=UTC))


class TestGetHeaders:
    def test_headers(self) -> None:
        headers = _get_headers("server-token-123")
        assert headers["X-Postmark-Server-Token"] == "server-token-123"
        assert headers["Accept"] == "application/json"


class TestResolveFromdate:
    def test_full_refresh_endpoint_returns_none(self) -> None:
        config = POSTMARK_ENDPOINTS["templates"]
        result = _resolve_fromdate(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            logger=mock.MagicMock(),
        )
        assert result is None

    def test_uses_db_value_when_provided(self) -> None:
        config = POSTMARK_ENDPOINTS["bounces"]
        last_value = datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)
        now = datetime(2026, 5, 1, tzinfo=UTC)
        result = _resolve_fromdate(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=last_value,
            logger=mock.MagicMock(),
            now=now,
        )
        assert result == last_value

    def test_uses_lookback_when_no_db_value(self) -> None:
        config = POSTMARK_ENDPOINTS["bounces"]
        now = datetime(2026, 5, 1, tzinfo=UTC)
        result = _resolve_fromdate(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            logger=mock.MagicMock(),
            now=now,
        )
        assert result == now - timedelta(days=config.default_lookback_days)

    def test_clamps_to_max_window(self) -> None:
        config = POSTMARK_ENDPOINTS["outbound_messages"]
        now = datetime(2026, 5, 1, tzinfo=UTC)
        old_value = now - timedelta(days=120)
        logger = mock.MagicMock()
        result = _resolve_fromdate(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=old_value,
            logger=logger,
            now=now,
        )
        assert result == now - timedelta(days=POSTMARK_OUTBOUND_MAX_WINDOW_DAYS)
        logger.warning.assert_called_once()

    def test_skips_clamp_when_within_window(self) -> None:
        config = POSTMARK_ENDPOINTS["outbound_messages"]
        now = datetime(2026, 5, 1, tzinfo=UTC)
        recent = now - timedelta(days=10)
        logger = mock.MagicMock()
        result = _resolve_fromdate(
            config,
            should_use_incremental_field=True,
            db_incremental_field_last_value=recent,
            logger=logger,
            now=now,
        )
        assert result == recent
        logger.warning.assert_not_called()


class TestBuildParams:
    def test_paginated_with_fromdate(self) -> None:
        config = POSTMARK_ENDPOINTS["bounces"]
        fromdate = datetime(2026, 4, 1, tzinfo=UTC)
        params = _build_params(config, offset=1000, fromdate=fromdate)
        assert params["count"] == POSTMARK_PAGE_SIZE
        assert params["offset"] == 1000
        assert params["fromdate"] == "2026-04-01T00:00:00"

    def test_paginated_without_fromdate(self) -> None:
        config = POSTMARK_ENDPOINTS["bounces"]
        params = _build_params(config, offset=0, fromdate=None)
        assert "fromdate" not in params
        assert params["count"] == POSTMARK_PAGE_SIZE

    def test_unpaginated_endpoint_skips_count_offset(self) -> None:
        config = POSTMARK_ENDPOINTS["message_streams"]
        params = _build_params(config, offset=0, fromdate=None)
        assert "count" not in params
        assert "offset" not in params


class TestGetRows:
    def _build_session_mock(self, pages: list[dict]) -> mock.MagicMock:
        session = mock.MagicMock()
        session.get = mock.MagicMock(side_effect=[self._fake_response(p) for p in pages])
        return session

    def _fake_response(self, payload: dict, status_code: int = 200) -> mock.MagicMock:
        resp = mock.MagicMock()
        resp.status_code = status_code
        resp.ok = 200 <= status_code < 300
        resp.json.return_value = payload
        return resp

    def test_paginates_until_partial_page(self) -> None:
        full_page = {"TotalCount": 1500, "Bounces": [{"ID": i} for i in range(POSTMARK_PAGE_SIZE)]}
        last_page = {"TotalCount": 1500, "Bounces": [{"ID": i} for i in range(100)]}
        session = self._build_session_mock([full_page, full_page, last_page])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(
                get_rows(
                    server_token="t",
                    endpoint_name="bounces",
                    logger=mock.MagicMock(),
                )
            )

        assert sum(len(c) for c in chunks) == POSTMARK_PAGE_SIZE * 2 + 100
        assert session.get.call_count == 3

    def test_paginates_until_total_count_reached(self) -> None:
        page = {"TotalCount": POSTMARK_PAGE_SIZE, "Bounces": [{"ID": i} for i in range(POSTMARK_PAGE_SIZE)]}
        session = self._build_session_mock([page])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(
                get_rows(
                    server_token="t",
                    endpoint_name="bounces",
                    logger=mock.MagicMock(),
                )
            )

        assert sum(len(c) for c in chunks) == POSTMARK_PAGE_SIZE
        assert session.get.call_count == 1

    def test_unpaginated_message_streams(self) -> None:
        page = {"MessageStreams": [{"ID": "outbound"}, {"ID": "inbound"}]}
        session = self._build_session_mock([page])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(
                get_rows(
                    server_token="t",
                    endpoint_name="message_streams",
                    logger=mock.MagicMock(),
                )
            )

        assert chunks == [[{"ID": "outbound"}, {"ID": "inbound"}]]
        assert session.get.call_count == 1

    def test_429_raises_retryable(self) -> None:
        session = mock.MagicMock()
        session.get = mock.MagicMock(return_value=self._fake_response({}, status_code=429))

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            try:
                list(
                    get_rows(
                        server_token="t",
                        endpoint_name="bounces",
                        logger=mock.MagicMock(),
                    )
                )
                raise AssertionError("Expected PostmarkRetryableError")
            except PostmarkRetryableError:
                pass

    def test_unknown_endpoint_raises(self) -> None:
        try:
            list(get_rows(server_token="t", endpoint_name="not_real", logger=mock.MagicMock()))
            raise AssertionError("Expected ValueError")
        except ValueError:
            pass


class TestValidateCredentials:
    def _patch_session(self, status_code: int) -> mock.MagicMock:
        resp = mock.MagicMock(status_code=status_code, ok=200 <= status_code < 300, reason="reason")
        session = mock.MagicMock()
        session.get = mock.MagicMock(return_value=resp)
        return session

    def test_success(self) -> None:
        session = self._patch_session(200)
        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            ok, msg = validate_credentials("token")
        assert ok is True
        assert msg is None
        session.get.assert_called_once_with(f"{POSTMARK_BASE_URL}/server", timeout=10)

    def test_unauthorized(self) -> None:
        session = self._patch_session(401)
        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            ok, msg = validate_credentials("token")
        assert ok is False
        assert "Invalid" in (msg or "")

    def test_forbidden(self) -> None:
        session = self._patch_session(403)
        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            ok, msg = validate_credentials("token")
        assert ok is False
        assert "permissions" in (msg or "")

    def test_empty_token(self) -> None:
        ok, msg = validate_credentials("")
        assert ok is False
        assert msg


class TestPostmarkSource:
    def setup_method(self) -> None:
        self.source = PostmarkSource()
        self.team_id = 123
        self.config = PostmarkSourceConfig(server_api_token="server-token-test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.POSTMARK

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Postmark"
        assert config.label == "Postmark"
        assert config.releaseStatus == "alpha"
        assert config.featureFlag == "dwh_postmark"
        assert config.iconPath == "/static/services/postmark.png"
        assert config.unreleasedSource is None or config.unreleasedSource is False
        assert len(config.fields) == 1

        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "server_api_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

    def test_non_retryable_errors(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert "401 Client Error" in errors
        assert "403 Client Error" in errors
        assert "422 Client Error" in errors

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)

        by_name = {s.name: s for s in schemas}
        assert by_name["templates"].supports_incremental is False
        assert by_name["templates"].supports_append is False
        assert by_name["message_streams"].supports_incremental is False
        assert by_name["bounces"].supports_incremental is True
        assert by_name["bounces"].supports_append is True
        assert by_name["outbound_messages"].supports_incremental is True
        assert by_name["outbound_opens"].supports_incremental is True
        assert by_name["outbound_clicks"].supports_incremental is True

    def test_get_schemas_filtered(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["bounces"])
        assert len(schemas) == 1
        assert schemas[0].name == "bounces"

    def test_get_schemas_filtered_unknown(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @mock.patch("posthog.temporal.data_imports.sources.postmark.source.validate_postmark_credentials")
    def test_validate_credentials_success(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        ok, msg = self.source.validate_credentials(self.config, self.team_id)
        assert ok is True
        assert msg is None
        mock_validate.assert_called_once_with(self.config.server_api_token)

    @mock.patch("posthog.temporal.data_imports.sources.postmark.source.validate_postmark_credentials")
    def test_validate_credentials_failure(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (False, "Invalid Postmark Server API token")
        ok, msg = self.source.validate_credentials(self.config, self.team_id)
        assert ok is False
        assert msg == "Invalid Postmark Server API token"

    @mock.patch("posthog.temporal.data_imports.sources.postmark.source.postmark_source")
    def test_source_for_pipeline_non_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bounces"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once_with(
            server_token=self.config.server_api_token,
            endpoint_name="bounces",
            logger=inputs.logger,
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
        )

    @mock.patch("posthog.temporal.data_imports.sources.postmark.source.postmark_source")
    def test_source_for_pipeline_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "outbound_messages"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-04-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once_with(
            server_token=self.config.server_api_token,
            endpoint_name="outbound_messages",
            logger=inputs.logger,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-04-01T00:00:00Z",
        )

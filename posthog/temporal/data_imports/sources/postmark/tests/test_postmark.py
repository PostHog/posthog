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
    _resolve_fromdate,
    get_rows,
    postmark_source,
    validate_credentials,
)
from posthog.temporal.data_imports.sources.postmark.settings import (
    ENDPOINTS,
    POSTMARK_ENDPOINTS,
    POSTMARK_OUTBOUND_MAX_WINDOW_DAYS,
    POSTMARK_PAGE_SIZE,
)
from posthog.temporal.data_imports.sources.postmark.source import PostmarkSource


class TestFormatPostmarkDatetime:
    @parameterized.expand(
        [
            # tz-aware inputs preserve the wall-clock value; the offset is just stripped. The
            # watermark coming from the pipeline carries Postmark's own offset already, so this
            # round-trips regardless of how the Postmark account is configured.
            (
                "eastern_aware",
                datetime(2026, 5, 6, 7, 38, 18, tzinfo=timezone(timedelta(hours=-4))),
                "2026-05-06T07:38:18",
            ),
            ("utc_aware_preserved", datetime(2026, 5, 6, 11, 38, 18, tzinfo=UTC), "2026-05-06T11:38:18"),
            (
                "plus_ten_aware_preserved",
                datetime(2026, 3, 4, 12, 58, 14, tzinfo=timezone(timedelta(hours=10))),
                "2026-03-04T12:58:14",
            ),
            # Naive input is treated as UTC and converted to Eastern (the API's documented default).
            # March 4 is in EST (UTC-5). 02:58:14 UTC -> 21:58:14 EST on March 3.
            ("naive_fallback_winter", datetime(2026, 3, 4, 2, 58, 14), "2026-03-03T21:58:14"),
            # July is EDT (UTC-4). 12:00 UTC -> 08:00 EDT.
            ("naive_fallback_summer", datetime(2026, 7, 1, 12, 0, 0), "2026-07-01T08:00:00"),
        ]
    )
    def test_format(self, _name: str, value: datetime, expected: str) -> None:
        assert _format_postmark_datetime(value) == expected

    def test_no_offset_suffix(self) -> None:
        # Postmark rejects fromdate values that carry a timezone marker — confirm we never emit one.
        formatted = _format_postmark_datetime(datetime(2026, 3, 4, tzinfo=UTC))
        assert "+" not in formatted
        assert "Z" not in formatted
        assert formatted.count("-") == 2  # only the two date dashes


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
        # tz-aware inputs preserve their wall-clock value; only the offset gets stripped.
        fromdate = datetime(2026, 4, 1, tzinfo=UTC)
        params = _build_params(config, offset=1000, fromdate=fromdate)
        assert params["count"] == POSTMARK_PAGE_SIZE
        assert params["offset"] == 1000
        assert params["fromdate"] == "2026-04-01T00:00:00"
        assert "todate" not in params

    def test_paginated_with_todate(self) -> None:
        config = POSTMARK_ENDPOINTS["bounces"]
        todate = datetime(2026, 3, 1, tzinfo=UTC)
        params = _build_params(config, offset=0, fromdate=None, todate=todate)
        assert params["todate"] == "2026-03-01T00:00:00"
        assert "fromdate" not in params

    def test_paginated_without_fromdate(self) -> None:
        config = POSTMARK_ENDPOINTS["bounces"]
        params = _build_params(config, offset=0, fromdate=None)
        assert "fromdate" not in params
        assert "todate" not in params
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

    def test_incremental_two_phase_paging(self) -> None:
        """With both watermarks set, we issue a `todate=earliest` backfill request and a
        `fromdate=last` catch-up request — Stripe's two-phase pattern adapted for Postmark."""
        backfill_page = {"TotalCount": 1, "Bounces": [{"ID": 1}]}
        catchup_page = {"TotalCount": 1, "Bounces": [{"ID": 2}]}
        session = self._build_session_mock([backfill_page, catchup_page])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(
                get_rows(
                    server_token="t",
                    endpoint_name="bounces",
                    logger=mock.MagicMock(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2026, 4, 1, tzinfo=UTC),
                    db_incremental_field_earliest_value=datetime(2026, 3, 1, tzinfo=UTC),
                )
            )

        assert chunks == [[{"ID": 1}], [{"ID": 2}]]
        assert session.get.call_count == 2

        backfill_call, catchup_call = session.get.call_args_list
        # tz-aware inputs preserve their wall-clock value; offset stripped, no conversion.
        assert backfill_call.kwargs["params"]["todate"] == "2026-03-01T00:00:00"
        assert "fromdate" not in backfill_call.kwargs["params"]
        assert catchup_call.kwargs["params"]["fromdate"] == "2026-04-01T00:00:00"
        assert "todate" not in catchup_call.kwargs["params"]

    def test_incremental_skips_backfill_at_window_edge(self) -> None:
        """outbound_messages has a 45-day search window. If the earliest watermark is older than
        the window floor, backfill would 422 — skip it and only run the catch-up phase."""
        catchup_page = {"TotalCount": 0, "Messages": []}
        session = self._build_session_mock([catchup_page])
        earliest_at_edge = datetime.now(UTC) - timedelta(days=POSTMARK_OUTBOUND_MAX_WINDOW_DAYS + 5)

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            list(
                get_rows(
                    server_token="t",
                    endpoint_name="outbound_messages",
                    logger=mock.MagicMock(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime.now(UTC) - timedelta(days=1),
                    db_incremental_field_earliest_value=earliest_at_edge,
                )
            )

        assert session.get.call_count == 1
        only_call = session.get.call_args_list[0]
        assert "todate" not in only_call.kwargs["params"]
        assert "fromdate" in only_call.kwargs["params"]

    def test_incremental_field_overrides_config_default(self) -> None:
        """When `inputs.incremental_field` is set, honor it instead of always reaching for the
        config's default. (Today the values match per endpoint; this protects against silent
        override if the menu of options ever expands.)"""
        page = {"TotalCount": 0, "Bounces": []}
        session = self._build_session_mock([page])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            list(
                get_rows(
                    server_token="t",
                    endpoint_name="bounces",
                    logger=mock.MagicMock(),
                    should_use_incremental_field=True,
                    incremental_field="BouncedAt",
                    db_incremental_field_last_value=datetime(2026, 4, 1, tzinfo=UTC),
                )
            )

        assert session.get.call_count == 1

    def test_delivery_stats_yields_bounce_rows(self) -> None:
        """/deliverystats returns a single object with a Bounces[] rollup; we yield the rollup
        rows. InactiveMails (a scalar) is intentionally dropped — derive it from the raw bounces
        table if needed."""
        page = {
            "InactiveMails": 7,
            "Bounces": [
                {"Name": "All", "Count": 100},
                {"Name": "HardBounce", "Count": 12},
                {"Name": "SoftBounce", "Count": 4, "Type": "SoftBounce"},
            ],
        }
        session = self._build_session_mock([page])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(get_rows(server_token="t", endpoint_name="delivery_stats", logger=mock.MagicMock()))

        assert chunks == [page["Bounces"]]
        assert session.get.call_count == 1
        assert "fromdate" not in session.get.call_args_list[0].kwargs["params"]

    def test_delivery_stats_empty(self) -> None:
        """An empty Bounces array yields nothing — caller iterates a 0-chunk generator."""
        page = {"InactiveMails": 0, "Bounces": []}
        session = self._build_session_mock([page])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(get_rows(server_token="t", endpoint_name="delivery_stats", logger=mock.MagicMock()))

        assert chunks == []

    def test_suppressions_fans_out_over_streams(self) -> None:
        """Suppressions are per-stream. We list /message-streams first, then call
        /message-streams/{id}/suppressions/dump per stream, enriching each row with MessageStreamID."""
        streams_page = {
            "MessageStreams": [
                {"ID": "outbound", "Name": "Default Transactional"},
                {"ID": "broadcast", "Name": "Default Broadcast"},
            ]
        }
        outbound_dump = {
            "Suppressions": [
                {
                    "EmailAddress": "a@example.com",
                    "SuppressionReason": "HardBounce",
                    "Origin": "Recipient",
                    "CreatedAt": "2026-04-01T12:00:00Z",
                },
            ]
        }
        broadcast_dump = {
            "Suppressions": [
                {
                    "EmailAddress": "b@example.com",
                    "SuppressionReason": "ManualSuppression",
                    "Origin": "Customer",
                    "CreatedAt": "2026-04-02T12:00:00Z",
                },
            ]
        }
        session = self._build_session_mock([streams_page, outbound_dump, broadcast_dump])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(get_rows(server_token="t", endpoint_name="suppressions", logger=mock.MagicMock()))

        flat = [row for chunk in chunks for row in chunk]
        assert flat == [
            {
                "EmailAddress": "a@example.com",
                "SuppressionReason": "HardBounce",
                "Origin": "Recipient",
                "CreatedAt": "2026-04-01T12:00:00Z",
                "MessageStreamID": "outbound",
            },
            {
                "EmailAddress": "b@example.com",
                "SuppressionReason": "ManualSuppression",
                "Origin": "Customer",
                "CreatedAt": "2026-04-02T12:00:00Z",
                "MessageStreamID": "broadcast",
            },
        ]
        # 1 list + 1 dump per stream
        assert session.get.call_count == 3
        called_paths = [c.args[0] for c in session.get.call_args_list]
        assert called_paths[0].endswith("/message-streams")
        assert called_paths[1].endswith("/message-streams/outbound/suppressions/dump")
        assert called_paths[2].endswith("/message-streams/broadcast/suppressions/dump")

    def test_suppressions_no_streams(self) -> None:
        """Account with no message streams (degenerate case) yields nothing and never calls
        the dump endpoint."""
        session = self._build_session_mock([{"MessageStreams": []}])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(get_rows(server_token="t", endpoint_name="suppressions", logger=mock.MagicMock()))

        assert chunks == []
        assert session.get.call_count == 1

    def test_suppressions_skips_empty_per_stream_dumps(self) -> None:
        """Streams with no suppressions yield zero chunks for that stream; other streams still
        produce rows."""
        session = self._build_session_mock(
            [
                {"MessageStreams": [{"ID": "outbound"}, {"ID": "broadcast"}]},
                {"Suppressions": []},
                {
                    "Suppressions": [
                        {
                            "EmailAddress": "x@example.com",
                            "SuppressionReason": "HardBounce",
                            "Origin": "Recipient",
                            "CreatedAt": "2026-04-02T12:00:00Z",
                        }
                    ]
                },
            ]
        )

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(get_rows(server_token="t", endpoint_name="suppressions", logger=mock.MagicMock()))

        flat = [row for chunk in chunks for row in chunk]
        assert flat == [
            {
                "EmailAddress": "x@example.com",
                "SuppressionReason": "HardBounce",
                "Origin": "Recipient",
                "CreatedAt": "2026-04-02T12:00:00Z",
                "MessageStreamID": "broadcast",
            }
        ]

    def test_incremental_skipped_when_no_field_configured(self) -> None:
        """templates has no incremental_field_api_name — even if the pipeline asks for incremental,
        the source falls back to a single full-refresh page with no fromdate."""
        page = {"Templates": [{"TemplateId": 1}]}
        session = self._build_session_mock([page])

        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            chunks = list(
                get_rows(
                    server_token="t",
                    endpoint_name="templates",
                    logger=mock.MagicMock(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value="2026-04-01T00:00:00Z",
                    db_incremental_field_earliest_value="2026-03-01T00:00:00Z",
                )
            )

        assert chunks == [[{"TemplateId": 1}]]
        assert session.get.call_count == 1
        only_call = session.get.call_args_list[0]
        assert "fromdate" not in only_call.kwargs["params"]
        assert "todate" not in only_call.kwargs["params"]


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

    def test_forbidden_at_source_create_is_accepted(self) -> None:
        """At source-create (no schema_name) we accept 403: the token is real but may legitimately
        only be scoped to a subset of endpoints. Per-schema 403 is still a hard fail."""
        session = self._patch_session(403)
        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            ok, msg = validate_credentials("token")
        assert ok is True
        assert msg is None

    def test_forbidden_per_schema_is_rejected(self) -> None:
        session = self._patch_session(403)
        with mock.patch(
            "posthog.temporal.data_imports.sources.postmark.postmark.make_tracked_session",
            return_value=session,
        ):
            ok, msg = validate_credentials("token", schema_name="bounces")
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

    def test_get_source_config(self) -> None:
        # Asserts on properties with semantic weight (gating + auth shape); not every literal.
        config = self.source.get_source_config
        assert config.releaseStatus == "alpha"
        assert config.featureFlag == "dwh_postmark"
        assert not config.unreleasedSource

        assert len(config.fields) == 1
        token_field = config.fields[0]
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

    def test_get_schemas(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {s.name for s in schemas} == set(ENDPOINTS)

        by_name = {s.name: s for s in schemas}
        assert by_name["templates"].supports_incremental is False
        assert by_name["templates"].supports_append is False
        assert by_name["message_streams"].supports_incremental is False
        assert by_name["delivery_stats"].supports_incremental is False
        assert by_name["suppressions"].supports_incremental is False
        assert by_name["bounces"].supports_incremental is True
        assert by_name["bounces"].supports_append is True
        assert by_name["outbound_messages"].supports_incremental is True
        assert by_name["outbound_opens"].supports_incremental is True
        assert by_name["outbound_clicks"].supports_incremental is True

    def test_get_schemas_filtered(self) -> None:
        assert [s.name for s in self.source.get_schemas(self.config, self.team_id, names=["bounces"])] == ["bounces"]
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @mock.patch("posthog.temporal.data_imports.sources.postmark.source.postmark_source")
    def test_source_for_pipeline_non_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bounces"
        inputs.should_use_incremental_field = False
        inputs.incremental_field = "BouncedAt"
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.db_incremental_field_earliest_value = "2025-12-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once_with(
            server_token=self.config.server_api_token,
            endpoint_name="bounces",
            logger=inputs.logger,
            should_use_incremental_field=False,
            incremental_field=None,
            db_incremental_field_last_value=None,
            db_incremental_field_earliest_value=None,
        )

    @mock.patch("posthog.temporal.data_imports.sources.postmark.source.postmark_source")
    def test_source_for_pipeline_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "outbound_messages"
        inputs.should_use_incremental_field = True
        inputs.incremental_field = "ReceivedAt"
        inputs.db_incremental_field_last_value = "2026-04-01T00:00:00Z"
        inputs.db_incremental_field_earliest_value = "2026-03-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, inputs)

        mock_source.assert_called_once_with(
            server_token=self.config.server_api_token,
            endpoint_name="outbound_messages",
            logger=inputs.logger,
            should_use_incremental_field=True,
            incremental_field="ReceivedAt",
            db_incremental_field_last_value="2026-04-01T00:00:00Z",
            db_incremental_field_earliest_value="2026-03-01T00:00:00Z",
        )

    @parameterized.expand(
        [
            ("outbound_messages", "desc"),
            ("outbound_opens", "desc"),
            ("outbound_clicks", "desc"),
            ("bounces", "desc"),
            ("inbound_messages", "desc"),
            ("templates", "asc"),
            ("message_streams", "asc"),
            ("delivery_stats", "asc"),
            ("suppressions", "asc"),
        ]
    )
    def test_postmark_source_sort_mode(self, endpoint: str, expected_sort_mode: str) -> None:
        """Postmark list endpoints return rows DESC by their time column with no `sorting=` to flip
        that, so incremental endpoints must declare sort_mode='desc' to match the pipeline's
        watermark expectations. Full-refresh endpoints can stay 'asc' (their order is irrelevant)."""
        response = postmark_source(
            server_token="t",
            endpoint_name=endpoint,
            logger=mock.MagicMock(),
        )
        assert response.sort_mode == expected_sort_mode

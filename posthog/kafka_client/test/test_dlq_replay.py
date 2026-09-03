from unittest import TestCase

from parameterized import parameterized

from posthog.kafka_client.dlq_replay import REPLAY_COUNT_HEADER, build_replay_headers


class BuildReplayHeadersTest(TestCase):
    def test_strips_diagnostics_keeps_originals_and_sets_first_replay_count(self) -> None:
        headers = [
            ("token", b"phc_abc"),
            ("team_id", b"42"),
            ("error_message", b"boom"),
            ("error_name", b"ValueError"),
            ("failed_at", b"2026-09-03T00:00:00Z"),
            ("source_topic", b"ingestion-traces"),
            ("source_partition", b"3"),
            ("source_offset", b"17"),
        ]

        result = build_replay_headers(headers, max_replays=2)

        assert result is not None
        as_dict = dict(result)
        assert as_dict == {"token": b"phc_abc", "team_id": b"42", REPLAY_COUNT_HEADER: b"1"}

    def test_none_headers_yields_only_replay_count(self) -> None:
        result = build_replay_headers(None, max_replays=2)
        assert result == [(REPLAY_COUNT_HEADER, b"1")]

    @parameterized.expand(
        [
            ("first_replay", 0, 2, b"1"),
            ("second_replay", 1, 2, b"2"),
            ("higher_cap", 3, 5, b"4"),
        ]
    )
    def test_increments_existing_replay_count(
        self, _name: str, current: int, max_replays: int, expected: bytes
    ) -> None:
        headers = [(REPLAY_COUNT_HEADER, str(current).encode("utf-8"))]

        result = build_replay_headers(headers, max_replays=max_replays)

        assert result is not None
        assert dict(result)[REPLAY_COUNT_HEADER] == expected
        assert sum(1 for key, _ in result if key == REPLAY_COUNT_HEADER) == 1

    @parameterized.expand(
        [
            ("at_cap", 2, 2),
            ("over_cap", 5, 2),
            ("zero_cap", 0, 0),
        ]
    )
    def test_returns_none_when_exhausted(self, _name: str, current: int, max_replays: int) -> None:
        headers = [(REPLAY_COUNT_HEADER, str(current).encode("utf-8"))]

        assert build_replay_headers(headers, max_replays=max_replays) is None

    def test_garbage_replay_count_treated_as_zero(self) -> None:
        result = build_replay_headers([(REPLAY_COUNT_HEADER, b"not-a-number")], max_replays=2)

        assert result is not None
        assert dict(result)[REPLAY_COUNT_HEADER] == b"1"

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.query_scan.flag import DEFAULT_EVENT_RATIO, DEFAULT_FLOOR_MS, DEFAULT_PERSONS_RATIO, _parse


class TestQueryScanFlagPayload(SimpleTestCase):
    @parameterized.expand(
        [
            ("json string", '{"floor_ms": 2500, "persons_ratio": 0.8}', 2500, DEFAULT_EVENT_RATIO, 0.8),
            ("dict", {"floor_ms": 2500.0, "event_ratio": 1}, 2500, 1.0, DEFAULT_PERSONS_RATIO),
            (
                "typos take the default",
                {"floor_ms": "2500", "event_ratio": True},
                DEFAULT_FLOOR_MS,
                DEFAULT_EVENT_RATIO,
                DEFAULT_PERSONS_RATIO,
            ),
            ("not json", "floor_ms=2500", DEFAULT_FLOOR_MS, DEFAULT_EVENT_RATIO, DEFAULT_PERSONS_RATIO),
            ("no payload", None, DEFAULT_FLOOR_MS, DEFAULT_EVENT_RATIO, DEFAULT_PERSONS_RATIO),
        ]
    )
    def test_each_threshold_falls_back_on_its_own(self, _name, payload, floor_ms, event_ratio, persons_ratio) -> None:
        flag = _parse("show", payload)

        assert (flag.mode, flag.floor_ms, flag.event_ratio, flag.persons_ratio) == (
            "show",
            floor_ms,
            event_ratio,
            persons_ratio,
        )

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.query_scan import flag
from posthog.query_scan.flag import DEFAULT_EVENT_RATIO, DEFAULT_FLOOR_MS, DEFAULT_PERSONS_RATIO, get_query_scan_flag

if TYPE_CHECKING:
    from posthog.models.team.team import Team

TEAM = cast(
    "Team",
    SimpleNamespace(
        id=42,
        uuid=uuid.UUID("00000000-0000-0000-0000-0000000000ff"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        organization_id=uuid.UUID("00000000-0000-0000-0000-00000000000a"),
    ),
)


class TestQueryScanFlag(SimpleTestCase):
    def test_evaluates_on_the_organization_and_the_project(self) -> None:
        payload = '{"floor_ms": 2000, "event_ratio": 0.2, "persons_ratio": 0.7}'
        with patch.object(flag.posthoganalytics, "get_feature_flag_result") as get_result:
            get_result.return_value = SimpleNamespace(variant="show", payload=payload)
            result = get_query_scan_flag(TEAM)

        assert result is not None
        self.assertEqual(result.mode, "show")
        self.assertEqual(result.floor_ms, 2000)
        self.assertEqual(result.event_ratio, 0.2)
        self.assertEqual(result.persons_ratio, 0.7)

        get_result.assert_called_once()
        kwargs = get_result.call_args.kwargs
        self.assertEqual(kwargs["groups"]["organization"], str(TEAM.organization_id))
        self.assertEqual(kwargs["group_properties"]["organization"]["id"], str(TEAM.organization_id))
        self.assertEqual(kwargs["groups"]["project"], str(TEAM.id))
        self.assertEqual(kwargs["group_properties"]["project"]["id"], str(TEAM.id))

    @parameterized.expand(
        [
            ("no payload", "show", None, (DEFAULT_FLOOR_MS, DEFAULT_EVENT_RATIO, DEFAULT_PERSONS_RATIO)),
            ("not json", "show", "not json", (DEFAULT_FLOOR_MS, DEFAULT_EVENT_RATIO, DEFAULT_PERSONS_RATIO)),
            (
                "wrong types",
                "show",
                {"floor_ms": True, "event_ratio": "0.2"},
                (DEFAULT_FLOOR_MS, DEFAULT_EVENT_RATIO, DEFAULT_PERSONS_RATIO),
            ),
            ("float floor", "show", {"floor_ms": 1500.0}, (1500, DEFAULT_EVENT_RATIO, DEFAULT_PERSONS_RATIO)),
            ("boolean flag", "on", None, None),
        ]
    )
    def test_reads_the_variant_and_falls_back_to_default_thresholds(
        self, _name: str, variant: str, payload: object, expected: tuple[int, float, float] | None
    ) -> None:
        with patch.object(flag.posthoganalytics, "get_feature_flag_result") as get_result:
            get_result.return_value = SimpleNamespace(variant=variant, payload=payload)
            result = get_query_scan_flag(TEAM)

        if expected is None:
            self.assertIsNone(result)
            return
        assert result is not None
        self.assertEqual((result.floor_ms, result.event_ratio, result.persons_ratio), expected)

from datetime import UTC, datetime

import pytest

from posthog.settings.experiments import _exposure_event_cutoff

CLOUD_CUTOFF = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "env_value,cloud_deployment,debug,expected",
    [
        (None, "US", False, CLOUD_CUTOFF),
        (None, "EU", False, CLOUD_CUTOFF),
        (None, "DEV", False, CLOUD_CUTOFF),
        (None, None, False, None),
        ("", None, False, None),
        (None, "E2E", False, None),
        (None, None, True, None),
        ("2026-12-01T10:00:00", None, False, datetime(2026, 12, 1, 10, tzinfo=UTC)),
        ("2026-12-01T10:00:00+02:00", "US", False, datetime(2026, 12, 1, 8, tzinfo=UTC)),
    ],
)
def test_exposure_event_cutoff(
    env_value: str | None, cloud_deployment: str | None, debug: bool, expected: datetime | None
) -> None:
    assert _exposure_event_cutoff(env_value, cloud_deployment, debug) == expected

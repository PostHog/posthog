"""Repository-root pytest configuration.

Loaded by pytest for every test path (the rootdir conftest is always imported),
so it is the one place that can patch the third-party `pytest-durations` plugin
before it measures anything.
"""

from __future__ import annotations

from contextlib import contextmanager

try:
    from pytest_durations.measure import MeasureDuration
    from pytest_durations.plugin import PytestDurationPlugin
except ImportError:  # pytest-durations is a CI-only dev dependency
    MeasureDuration = PytestDurationPlugin = None  # type: ignore[assignment, misc]


def _clamp_pytest_durations_to_non_negative() -> None:
    """Stop `pytest-durations` from reporting negative phase durations.

    The plugin attributes shared (session/package/module/class-scoped) fixture
    time away from a test's own setup/teardown by subtracting the accumulated
    shared-fixture duration (`PytestDurationPlugin.pytest_runtest_setup` /
    `pytest_runtest_teardown`). With a long package-scoped fixture -- our
    `django_db_setup`, which runs the full migration set on schema-cache-miss
    shards -- that subtraction exceeds the phase's own wall time and drives the
    reported "test setup" grand total negative. A measured phase cannot take
    negative time, so clamp each recorded measurement to zero.
    """
    if PytestDurationPlugin is None:
        return
    if getattr(PytestDurationPlugin._measure, "_clamps_negatives", False):
        return  # idempotent: a rootdir conftest can be imported more than once

    @contextmanager
    def _measure(self, category, key):  # type: ignore[no-untyped-def]
        measurements = self.measurements[category]
        with MeasureDuration() as measurement:
            yield measurement
        measurements.setdefault(key, []).append(max(0.0, measurement.duration))

    _measure._clamps_negatives = True  # type: ignore[attr-defined]
    PytestDurationPlugin._measure = _measure  # type: ignore[method-assign]


_clamp_pytest_durations_to_non_negative()

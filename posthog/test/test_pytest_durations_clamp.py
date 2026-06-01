import pytest

pytest_durations_plugin = pytest.importorskip("pytest_durations.plugin")
pytest_durations_types = pytest.importorskip("pytest_durations.types")

PytestDurationPlugin = pytest_durations_plugin.PytestDurationPlugin
Category = pytest_durations_types.Category


def test_root_conftest_applied_clamp_patch():
    assert getattr(PytestDurationPlugin._measure, "_clamps_negatives", False)


@pytest.mark.parametrize("category", [Category.TEST_SETUP, Category.TEST_TEARDOWN])
def test_over_subtracted_phase_is_clamped_to_zero(category):
    plugin = PytestDurationPlugin()
    key = ("module", "test")

    with plugin._measure(category, key) as measurement:
        # Reproduce a shared-fixture over-subtraction (e.g. package-scoped
        # django_db_setup) pushing the phase below zero.
        measurement.duration -= 100.0

    assert plugin.measurements[category][key] == [0.0]


def test_positive_phase_duration_is_preserved():
    plugin = PytestDurationPlugin()
    key = ("module", "test")

    with plugin._measure(Category.TEST_SETUP, key) as measurement:
        measurement.duration += 5.0

    [duration] = plugin.measurements[Category.TEST_SETUP][key]
    assert duration >= 5.0

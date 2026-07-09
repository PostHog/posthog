from posthog.test.base import BaseTest

from posthog.models.property import BehavioralPropertyType, Property


class TestBehavioralPropertyDateRangeValidation(BaseTest):
    """Validation of the explicit_datetime / explicit_datetime_to combo on behavioral cohort filters."""

    def _build(self, **overrides) -> Property:
        defaults: dict = {
            "type": "behavioral",
            "key": "$pageview",
            "event_type": "events",
        }
        defaults.update(overrides)
        return Property(**defaults)

    def test_performed_event_accepts_explicit_datetime_range(self) -> None:
        # Should not raise
        self._build(
            value=BehavioralPropertyType.PERFORMED_EVENT,
            explicit_datetime="-30d",
            explicit_datetime_to="-7d",
        )

    def test_performed_event_multiple_accepts_explicit_datetime_range(self) -> None:
        self._build(
            value=BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE,
            operator_value=3,
            explicit_datetime="-30d",
            explicit_datetime_to="-7d",
        )

    def test_performed_event_still_accepts_single_bound(self) -> None:
        self._build(
            value=BehavioralPropertyType.PERFORMED_EVENT,
            explicit_datetime="-30d",
        )

    def test_performed_event_rejects_only_upper_bound(self) -> None:
        # explicit_datetime_to alone does not satisfy any conditional combo
        with self.assertRaises(ValueError):
            self._build(
                value=BehavioralPropertyType.PERFORMED_EVENT,
                explicit_datetime_to="-7d",
            )

    def test_performed_event_first_time_accepts_explicit_datetime(self) -> None:
        self._build(
            value=BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
            explicit_datetime="-30d",
        )

    def test_performed_event_first_time_accepts_explicit_datetime_range(self) -> None:
        self._build(
            value=BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
            explicit_datetime="-30d",
            explicit_datetime_to="-7d",
        )

    def test_performed_event_first_time_still_accepts_time_value_interval(self) -> None:
        # Legacy shape emitted by the old UI must keep validating so saved cohorts don't break
        self._build(
            value=BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
            time_value=30,
            time_interval="day",
        )

    def test_performed_event_first_time_rejects_no_time_fields(self) -> None:
        with self.assertRaises(ValueError):
            self._build(value=BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME)

    def test_performed_event_first_time_rejects_only_upper_bound(self) -> None:
        with self.assertRaises(ValueError):
            self._build(
                value=BehavioralPropertyType.PERFORMED_EVENT_FIRST_TIME,
                explicit_datetime_to="-7d",
            )

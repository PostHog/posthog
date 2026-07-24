from posthog.test.base import BaseTest

from parameterized import parameterized

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


class TestBehavioralPropertyValueAlias(BaseTest):
    """Some cohort filter generators store "performed_event_multiple_times" instead of
    BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE's canonical "performed_event_multiple".
    The alias must resolve to that type's validation rules, not just skip validation."""

    def _build(self, **overrides) -> Property:
        defaults: dict = {
            "type": "behavioral",
            "key": "$pageview",
            "event_type": "events",
            "value": "performed_event_multiple_times",
        }
        defaults.update(overrides)
        return Property(**defaults)

    def test_accepts_time_bound_like_canonical_type(self) -> None:
        prop = self._build(operator_value=1, time_value=3650, time_interval="day")
        self.assertEqual(prop.value, BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE)

    def test_still_requires_operator_value(self) -> None:
        # PERFORMED_EVENT_MULTIPLE's unconditional required attrs (VALIDATE_BEHAVIORAL_PROP_TYPES)
        # must still apply through the alias, not just its conditional time-bound rules.
        with self.assertRaises(ValueError):
            self._build(time_value=3650, time_interval="day")


class TestBehavioralPropertyBytecodeCondition(BaseTest):
    """The realtime-cohort builder can express an unbounded "did this person ever do X"
    condition purely via compiled bytecode/conditionHash, with no time_value/time_interval/
    explicit_datetime set. That's a deliberately unbounded condition, not a malformed one."""

    def _build(self, **overrides) -> Property:
        defaults: dict = {
            "type": "behavioral",
            "key": "$pageview",
            "event_type": "events",
            "value": BehavioralPropertyType.PERFORMED_EVENT,
            "bytecode": ["_H", 1, 32, "$pageview", 32, "event", 1, 1, 11],
            "conditionHash": "f9c616030a87e68f",
        }
        defaults.update(overrides)
        return Property(**defaults)

    @parameterized.expand(
        [
            ("performed_event", BehavioralPropertyType.PERFORMED_EVENT, {}),
            (
                "performed_event_multiple",
                BehavioralPropertyType.PERFORMED_EVENT_MULTIPLE,
                {"operator_value": 1},
            ),
        ]
    )
    def test_accepts_bytecode_condition_with_no_time_bound(self, _name, value, extra_kwargs) -> None:
        self._build(value=value, **extra_kwargs)  # should not raise

    @parameterized.expand(
        [
            ("no_conditions_at_all", {"bytecode": None, "conditionHash": None}),
            # {conditionHash, bytecode} requires both, matching how the cohort backend
            # always compiles them together — a partial pair isn't a valid compiled condition.
            ("bytecode_without_condition_hash", {"conditionHash": None}),
        ]
    )
    def test_rejects_incomplete_bytecode_condition(self, _name, overrides) -> None:
        with self.assertRaises(ValueError):
            self._build(**overrides)

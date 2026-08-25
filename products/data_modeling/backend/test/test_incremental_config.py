from datetime import UTC, date, datetime, timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from parameterized import parameterized

from products.data_modeling.backend.logic.incremental import (
    IncrementalConfig,
    IncrementalState,
    clear_incremental_state,
    definition_fingerprint,
    deserialize_watermark,
    get_incremental_config,
    get_incremental_state,
    set_incremental_state,
    window_start,
)
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery

QUERY = {"query": "SELECT toStartOfDay(timestamp) AS day, count() AS c FROM events GROUP BY day"}
CONFIG = IncrementalConfig(incremental_key="day", unique_key=("day",))


class TestIncrementalConfig(BaseTest):
    def _saved_query(self, **kwargs) -> DataWarehouseSavedQuery:
        return DataWarehouseSavedQuery.objects.create(team=self.team, name="daily_events", query=QUERY, **kwargs)

    @parameterized.expand(
        [
            ("absent", None),
            ("not_enabled", {"enabled": False, "incremental_key": "day", "unique_key": ["day"]}),
            ("no_key", {"enabled": True, "unique_key": ["day"]}),
            ("empty_unique_key", {"enabled": True, "incremental_key": "day", "unique_key": []}),
            ("unique_key_not_a_list", {"enabled": True, "incremental_key": "day", "unique_key": "day"}),
        ]
    )
    def test_incomplete_config_reads_as_off(self, _name: str, raw: dict | None) -> None:
        """A half-written config must degrade to a full refresh rather than failing a run."""
        saved_query = self._saved_query(incremental_config=raw)

        assert get_incremental_config(saved_query) is None

    def test_lookback_is_clamped_and_defaulted(self) -> None:
        saved_query = self._saved_query(
            incremental_config={
                "enabled": True,
                "incremental_key": "day",
                "unique_key": ["day"],
                "lookback_seconds": 10**9,
            }
        )

        config = get_incremental_config(saved_query)
        assert config is not None
        assert config.lookback_seconds == 60 * 60 * 24 * 30

    def test_fingerprint_ignores_formatting_but_not_meaning(self) -> None:
        """Reformatting must not trigger a rebuild of a large table; a real edit must."""
        reformatted = {
            "query": "SELECT\n  toStartOfDay(timestamp) AS day,\n  count() AS c\n-- a note\nFROM events\nGROUP BY day"
        }
        edited = {"query": QUERY["query"] + " HAVING c > 1"}

        assert definition_fingerprint(QUERY, CONFIG) == definition_fingerprint(reformatted, CONFIG)
        assert definition_fingerprint(QUERY, CONFIG) != definition_fingerprint(edited, CONFIG)

    def test_fingerprint_covers_the_config(self) -> None:
        """Changing what the key means changes what the stored rows mean, so it must rebuild."""
        other = IncrementalConfig(incremental_key="day", unique_key=("day", "event"))

        assert definition_fingerprint(QUERY, CONFIG) != definition_fingerprint(QUERY, other)

    def test_a_lookback_change_alone_does_not_force_a_rebuild(self) -> None:
        """Lookback is operational: it changes how far future runs re-read, not what the stored
        rows mean. Fingerprinting it would rebuild a whole table for a knob tweak."""
        wider = IncrementalConfig(
            incremental_key=CONFIG.incremental_key,
            unique_key=CONFIG.unique_key,
            lookback_seconds=CONFIG.lookback_seconds + 3600,
        )

        assert definition_fingerprint(QUERY, CONFIG) == definition_fingerprint(QUERY, wider)

    def test_fingerprint_ignores_unique_key_order(self) -> None:
        a = IncrementalConfig(incremental_key="day", unique_key=("day", "event"))
        b = IncrementalConfig(incremental_key="day", unique_key=("event", "day"))

        assert definition_fingerprint(QUERY, a) == definition_fingerprint(QUERY, b)

    def test_fingerprint_of_an_unparseable_query_is_none(self) -> None:
        assert definition_fingerprint({"query": "SELECT FROM WHERE"}, CONFIG) is None

    @parameterized.expand(
        [
            ("datetime", datetime(2026, 8, 1, 12, 30, tzinfo=UTC), datetime),
            ("date", date(2026, 8, 1), date),
            ("int", 42, int),
            ("float", 42.5, float),
            ("date_like_string", "2026-08-01", str),
            ("datetime_like_string", "2026-08-01T12:30:00+00:00", str),
        ]
    )
    def test_state_round_trips_a_watermark_by_type(self, _name: str, watermark, expected_type: type) -> None:
        """The persisted type tag is what keeps a string key stable: a value such as
        toString(toDate(timestamp)) looks like a date, and sniffing it back into one would compare
        a Date constant against a String column on the next run."""
        saved_query = self._saved_query()

        set_incremental_state(saved_query, watermark=watermark, fingerprint="abc", mode="incremental")

        saved_query.refresh_from_db()
        state = get_incremental_state(saved_query)
        restored = deserialize_watermark(state.watermark, state.watermark_type)
        assert restored == watermark
        assert type(restored) is expected_type
        assert state.definition_fingerprint == "abc"
        assert state.last_run_mode == "incremental"

    @parameterized.expand(
        [
            ("future_datetime", lambda now: now + timedelta(hours=23), lambda now: now),
            ("past_datetime", lambda now: now - timedelta(hours=1), lambda now: now - timedelta(hours=1)),
            ("future_date", lambda now: (now + timedelta(days=3)).date(), lambda now: now.date()),
            # Strings never clamp: their order is not temporal, whatever they look like.
            ("date_like_string", lambda now: "2999-01-01", lambda now: "2999-01-01"),
        ]
    )
    def test_a_temporal_watermark_never_persists_past_now(self, _name: str, make_watermark, make_expected) -> None:
        """Capture accepts future-dated events, and one of them would advance the watermark past
        data that has not arrived yet, so later runs silently skip the legitimate rows between."""
        saved_query = self._saved_query()
        now = timezone.now()

        set_incremental_state(saved_query, watermark=make_watermark(now), fingerprint="abc", mode="incremental")

        saved_query.refresh_from_db()
        state = get_incremental_state(saved_query)
        restored = deserialize_watermark(state.watermark, state.watermark_type)
        expected = make_expected(now)
        if isinstance(expected, datetime):
            # "now" moves between building the expectation and the clamp reading its own clock.
            assert expected <= restored <= timezone.now()
        else:
            assert restored == expected

    @parameterized.expand(
        [
            ("datetime_string", "2026-08-01T12:30:00+00:00"),
            ("date_string", "2026-08-01"),
            ("non_iso_string", "not-a-date"),
            ("integer", 42),
        ]
    )
    def test_an_untagged_watermark_reads_as_absent(self, _name: str, stored) -> None:
        """Without a tag the value's type would have to be guessed, which is what the tag exists
        to prevent. Absent routes the run to one full refresh, which re-records a tagged state."""
        assert deserialize_watermark(stored, None) is None

    def test_a_corrupted_tagged_watermark_reads_as_absent(self) -> None:
        """A watermark the tag cannot parse routes the run to a full refresh instead of failing it."""
        assert deserialize_watermark("not-a-datetime", "datetime") is None

    def test_setting_state_leaves_a_concurrent_config_edit_alone(self) -> None:
        """The API writes config while a run writes state. Losing the config edit would silently
        turn incremental off, or worse, apply the old key to new rows."""
        saved_query = self._saved_query()

        edited = DataWarehouseSavedQuery.objects.get(pk=saved_query.pk)
        edited.incremental_config = {"enabled": True, "incremental_key": "day", "unique_key": ["day"]}
        edited.save(update_fields=["incremental_config"])

        set_incremental_state(saved_query, watermark=1, fingerprint="abc", mode="incremental")

        saved_query.refresh_from_db()
        assert get_incremental_config(saved_query) is not None
        assert get_incremental_state(saved_query).watermark == 1

    def test_clearing_state_drops_progress_but_keeps_config(self) -> None:
        saved_query = self._saved_query(
            incremental_config={"enabled": True, "incremental_key": "day", "unique_key": ["day"]}
        )
        set_incremental_state(saved_query, watermark=5, fingerprint="abc", mode="incremental")

        clear_incremental_state(saved_query)

        saved_query.refresh_from_db()
        state = get_incremental_state(saved_query)
        assert state.watermark is None
        assert state.watermark_type is None
        assert get_incremental_config(saved_query) is not None

    @parameterized.expand(
        [
            ("no_watermark", None, None, 3600, None),
            (
                "datetime_shifts_back",
                datetime(2026, 8, 2, tzinfo=UTC),
                "datetime",
                3600,
                datetime(2026, 8, 1, 23, tzinfo=UTC),
            ),
            (
                "persisted_datetime_string_shifts_back",
                "2026-08-02T00:00:00+00:00",
                "datetime",
                3600,
                datetime(2026, 8, 1, 23, tzinfo=UTC),
            ),
            (
                "datetime_no_lookback",
                datetime(2026, 8, 2, tzinfo=UTC),
                "datetime",
                0,
                datetime(2026, 8, 2, tzinfo=UTC),
            ),
            ("integer_key_ignores_lookback", 42, "int", 3600, 42),
            ("string_key_ignores_lookback", "2026-08-02", "string", 3600, "2026-08-02"),
        ]
    )
    def test_window_start(self, _name: str, watermark, watermark_type, lookback: int, expected) -> None:
        config = IncrementalConfig(incremental_key="day", unique_key=("day",), lookback_seconds=lookback)

        assert window_start(IncrementalState(watermark=watermark, watermark_type=watermark_type), config) == expected

    def test_lookback_applies_to_a_watermark_persisted_through_the_database(self) -> None:
        """The stored form of a datetime watermark is an ISO string. The lookback has to shift the
        deserialized datetime — shifting nothing because the value is a string is how late-arriving
        rows get silently missed."""
        saved_query = self._saved_query()
        watermark = datetime(2026, 8, 2, tzinfo=UTC)
        set_incremental_state(saved_query, watermark=watermark, fingerprint="abc", mode="incremental")

        saved_query.refresh_from_db()
        config = IncrementalConfig(incremental_key="day", unique_key=("day",), lookback_seconds=90)

        assert window_start(get_incremental_state(saved_query), config) == watermark - timedelta(seconds=90)

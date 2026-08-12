from datetime import UTC, date, datetime, timedelta

from posthog.test.base import BaseTest

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

    def test_fingerprint_ignores_unique_key_order(self) -> None:
        a = IncrementalConfig(incremental_key="day", unique_key=("day", "event"))
        b = IncrementalConfig(incremental_key="day", unique_key=("event", "day"))

        assert definition_fingerprint(QUERY, a) == definition_fingerprint(QUERY, b)

    def test_fingerprint_of_an_unparseable_query_is_none(self) -> None:
        assert definition_fingerprint({"query": "SELECT FROM WHERE"}, CONFIG) is None

    def test_state_round_trips_a_datetime_watermark(self) -> None:
        saved_query = self._saved_query()
        watermark = datetime(2026, 8, 1, 12, 30, tzinfo=UTC)

        set_incremental_state(saved_query, watermark=watermark, fingerprint="abc", mode="incremental")

        saved_query.refresh_from_db()
        state = get_incremental_state(saved_query)
        assert deserialize_watermark(state.watermark) == watermark
        assert state.definition_fingerprint == "abc"
        assert state.last_run_mode == "incremental"

    def test_state_round_trips_a_date_watermark(self) -> None:
        """A Date incremental key yields a plain date, which the JSON field cannot store, and which
        must come back as a date rather than a midnight datetime so it compares against a Date
        column as the right type."""
        saved_query = self._saved_query()

        set_incremental_state(saved_query, watermark=date(2026, 8, 1), fingerprint="abc", mode="incremental")

        saved_query.refresh_from_db()
        restored = deserialize_watermark(get_incremental_state(saved_query).watermark)
        assert restored == date(2026, 8, 1)
        assert not isinstance(restored, datetime)

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
        assert get_incremental_state(saved_query).watermark is None
        assert get_incremental_config(saved_query) is not None

    @parameterized.expand(
        [
            ("no_watermark", None, 3600, None),
            ("datetime_shifts_back", datetime(2026, 8, 2, tzinfo=UTC), 3600, datetime(2026, 8, 1, 23, tzinfo=UTC)),
            ("datetime_no_lookback", datetime(2026, 8, 2, tzinfo=UTC), 0, datetime(2026, 8, 2, tzinfo=UTC)),
            ("integer_key_ignores_lookback", 42, 3600, 42),
        ]
    )
    def test_window_start(self, _name: str, watermark, lookback: int, expected) -> None:
        config = IncrementalConfig(incremental_key="day", unique_key=("day",), lookback_seconds=lookback)

        assert window_start(IncrementalState(watermark=watermark), config) == expected

    def test_lookback_reaches_back_a_whole_number_of_seconds(self) -> None:
        config = IncrementalConfig(incremental_key="day", unique_key=("day",), lookback_seconds=90)
        watermark = datetime(2026, 8, 2, tzinfo=UTC)

        assert window_start(IncrementalState(watermark=watermark), config) == watermark - timedelta(seconds=90)

from posthog.test.base import BaseTest

from posthog.schema import DataWarehouseSyncWarning

from posthog.hogql.warehouse_warnings import accumulator_scope, install_accumulator, record_warnings, reset_accumulator


def _make_warning(table_name: str = "t", schema_name: str = "s") -> DataWarehouseSyncWarning:
    return DataWarehouseSyncWarning(
        table_name=table_name,
        schema_name=schema_name,
        source_type="Stripe",
        status="Failed",
        message=f"sync of `{table_name}` failed",
    )


class TestWarehouseWarningsAccumulator(BaseTest):
    def test_record_warnings_is_a_noop_outside_a_scope(self) -> None:
        # Should not raise — no accumulator installed.
        record_warnings([_make_warning()])

    def test_scope_collects_recorded_warnings(self) -> None:
        warning = _make_warning()
        with accumulator_scope() as acc:
            record_warnings([warning])
            assert list(acc.values()) == [warning]

    def test_scope_dedupes_by_table_and_schema(self) -> None:
        first = _make_warning(table_name="stripe_charge", schema_name="Charge")
        second_same_key = _make_warning(table_name="stripe_charge", schema_name="Charge")
        second_same_key.message = "updated message"
        different_key = _make_warning(table_name="stripe_charge", schema_name="Refund")

        with accumulator_scope() as acc:
            record_warnings([first, second_same_key, different_key])
            assert len(acc) == 2
            # Later write to the same key wins.
            assert acc[("stripe_charge", "Charge")].message == "updated message"

    def test_nested_scope_shares_parents_accumulator(self) -> None:
        outer_warning = _make_warning(table_name="t1")
        inner_warning = _make_warning(table_name="t2")

        with accumulator_scope() as outer:
            record_warnings([outer_warning])
            with accumulator_scope() as inner:
                assert inner is outer
                record_warnings([inner_warning])
            # Inner scope contributed; outer still owns the dict.
            assert len(outer) == 2

    def test_scope_resets_on_exception(self) -> None:
        class _ExpectedError(Exception):
            pass

        try:
            with accumulator_scope():
                record_warnings([_make_warning()])
                raise _ExpectedError()
        except _ExpectedError:
            pass

        # Accumulator should be torn down — a fresh scope sees no leftover state.
        with accumulator_scope() as acc:
            assert acc == {}

    def test_install_returns_none_token_when_already_installed(self) -> None:
        outer, outer_token = install_accumulator()
        try:
            inner, inner_token = install_accumulator()
            try:
                assert inner is outer
                assert inner_token is None
            finally:
                reset_accumulator(inner_token)
            # The outer accumulator is still active because inner didn't reset.
            record_warnings([_make_warning()])
            assert len(outer) == 1
        finally:
            reset_accumulator(outer_token)

import pytest

from posthog.temporal.data_imports.signals.registry import (
    _SIGNAL_TABLE_CONFIGS,
    SignalEmitterOutput,
    SignalSourceTableConfig,
    get_signal_config,
    is_signal_emission_registered,
    register_signal_source_table,
)

from products.data_warehouse.backend.types import ExternalDataSourceType


def _noop_emitter(team_id: int, record: dict) -> SignalEmitterOutput | None:
    return None


@pytest.fixture(autouse=True)
def _clean_registry():
    original = dict(_SIGNAL_TABLE_CONFIGS)
    yield
    _SIGNAL_TABLE_CONFIGS.clear()
    _SIGNAL_TABLE_CONFIGS.update(original)


class TestRegisterSignalSourceTable:
    def test_registers_and_retrieves_config(self):
        config = SignalSourceTableConfig(emitter=_noop_emitter, partition_field="created_at")
        register_signal_source_table(ExternalDataSourceType.ZENDESK, "tickets", config)

        assert get_signal_config("Zendesk", "tickets") is config

    def test_overwrites_existing_registration(self):
        config_a = SignalSourceTableConfig(emitter=_noop_emitter, partition_field="created_at")
        config_b = SignalSourceTableConfig(emitter=_noop_emitter, partition_field="updated_at")
        register_signal_source_table(ExternalDataSourceType.ZENDESK, "tickets", config_a)
        register_signal_source_table(ExternalDataSourceType.ZENDESK, "tickets", config_b)

        assert get_signal_config("Zendesk", "tickets") is config_b


class TestGetSignalConfig:
    @pytest.mark.parametrize(
        "source_type,schema_name",
        [
            ("NonExistent", "tickets"),
            ("Zendesk", "nonexistent_table"),
            ("", ""),
        ],
    )
    def test_returns_none_for_unregistered(self, source_type, schema_name):
        assert get_signal_config(source_type, schema_name) is None


class TestIsSignalEmissionRegistered:
    def test_true_when_registered(self):
        config = SignalSourceTableConfig(emitter=_noop_emitter, partition_field="time")
        register_signal_source_table(ExternalDataSourceType.ZENDESK, "ticket_metric_events", config)

        assert is_signal_emission_registered("Zendesk", "ticket_metric_events") is True

    def test_false_when_not_registered(self):
        assert is_signal_emission_registered("Zendesk", "organizations") is False


class TestZendeskTicketsAutoRegistered:
    def test_zendesk_tickets_registered_on_module_load(self):
        config = get_signal_config("Zendesk", "tickets")
        assert config is not None
        assert config.partition_field == "created_at"

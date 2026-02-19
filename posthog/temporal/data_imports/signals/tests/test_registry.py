import pytest

from pydantic import ValidationError

from posthog.temporal.data_imports.signals.registry import (
    _SIGNAL_TABLE_CONFIGS,
    SignalSourceTableConfig,
    get_signal_config,
    is_signal_emission_registered,
    register_signal_source_table,
)

from products.data_warehouse.backend.types import ExternalDataSourceType

_BASE_FIELDS = {"emitter": lambda tid, r: None, "partition_field": "created_at", "fields": ("id",)}


@pytest.fixture(autouse=True)
def _clean_registry():
    original = dict(_SIGNAL_TABLE_CONFIGS)
    yield
    _SIGNAL_TABLE_CONFIGS.clear()
    _SIGNAL_TABLE_CONFIGS.update(original)


class TestRegisterSignalSourceTable:
    def test_registers_and_retrieves_config(self):
        config = SignalSourceTableConfig(**_BASE_FIELDS)
        register_signal_source_table(ExternalDataSourceType.ZENDESK, "tickets", config)

        assert get_signal_config("Zendesk", "tickets") is config

    def test_overwrites_existing_registration(self):
        config_a = SignalSourceTableConfig(**_BASE_FIELDS)
        config_b = SignalSourceTableConfig(**{**_BASE_FIELDS, "partition_field": "updated_at"})
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
        config = SignalSourceTableConfig(**{**_BASE_FIELDS, "partition_field": "time"})
        register_signal_source_table(ExternalDataSourceType.ZENDESK, "ticket_metric_events", config)

        assert is_signal_emission_registered("Zendesk", "ticket_metric_events") is True

    def test_false_when_not_registered(self):
        assert is_signal_emission_registered("Zendesk", "organizations") is False


class TestSignalSourceTableConfigValidation:
    @pytest.mark.parametrize(
        "field_name",
        ["actionability_prompt", "summarization_prompt"],
    )
    def test_rejects_prompt_without_description_placeholder(self, field_name):
        with pytest.raises(ValidationError, match="must contain.*description.*placeholder"):
            SignalSourceTableConfig(
                **{
                    **_BASE_FIELDS,
                    field_name: "No placeholder here",
                    **(
                        {"description_summarization_threshold_chars": 2000}
                        if field_name == "summarization_prompt"
                        else {}
                    ),
                }
            )

    @pytest.mark.parametrize(
        "field_name",
        ["actionability_prompt", "summarization_prompt"],
    )
    def test_accepts_prompt_with_description_placeholder(self, field_name):
        config = SignalSourceTableConfig(
            **{
                **_BASE_FIELDS,
                field_name: "Analyze: {description}",
                **({"description_summarization_threshold_chars": 2000} if field_name == "summarization_prompt" else {}),
            }
        )
        assert getattr(config, field_name) is not None

    def test_rejects_summarization_prompt_without_threshold(self):
        with pytest.raises(ValidationError, match="must both be set or both be None"):
            SignalSourceTableConfig(**{**_BASE_FIELDS, "summarization_prompt": "Summarize: {description}"})

    def test_rejects_threshold_without_summarization_prompt(self):
        with pytest.raises(ValidationError, match="must both be set or both be None"):
            SignalSourceTableConfig(**{**_BASE_FIELDS, "description_summarization_threshold_chars": 2000})

    @pytest.mark.parametrize("value", [0, -1, -100])
    def test_rejects_non_positive_threshold(self, value):
        with pytest.raises(ValidationError, match="greater than 0"):
            SignalSourceTableConfig(
                **{
                    **_BASE_FIELDS,
                    "summarization_prompt": "Summarize: {description}",
                    "description_summarization_threshold_chars": value,
                }
            )

    def test_accepts_both_summarization_fields_set(self):
        config = SignalSourceTableConfig(
            **{
                **_BASE_FIELDS,
                "summarization_prompt": "Summarize: {description}",
                "description_summarization_threshold_chars": 2000,
            }
        )
        assert config.summarization_prompt is not None
        assert config.description_summarization_threshold_chars == 2000

    def test_accepts_both_summarization_fields_none(self):
        config = SignalSourceTableConfig(**_BASE_FIELDS)
        assert config.summarization_prompt is None
        assert config.description_summarization_threshold_chars is None


class TestZendeskTicketsAutoRegistered:
    def test_zendesk_tickets_registered_on_module_load(self):
        config = get_signal_config("Zendesk", "tickets")
        assert config is not None
        assert config.partition_field == "created_at"

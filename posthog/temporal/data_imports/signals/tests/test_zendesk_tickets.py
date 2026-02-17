import pytest

from posthog.temporal.data_imports.signals.zendesk_tickets import (
    EXTRA_FIELDS,
    ZENDESK_TICKETS_CONFIG,
    zendesk_ticket_emitter,
)


class TestZendeskTicketEmitter:
    def test_emits_signal_for_valid_ticket(self, zendesk_ticket_record):
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert result.source_type == "zendesk_ticket"
        assert result.source_id == "42"
        assert result.weight == 1.0
        assert "Dashboard charts not loading" in result.description
        assert "403 errors" in result.description

    def test_includes_status_in_description(self, zendesk_ticket_record):
        zendesk_ticket_record["status"] = "pending"
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert "Status: pending." in result.description

    def test_includes_priority_in_description(self, zendesk_ticket_record):
        zendesk_ticket_record["priority"] = "urgent"
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert "Priority: urgent." in result.description

    def test_omits_status_when_absent(self, zendesk_ticket_record):
        zendesk_ticket_record["status"] = None
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert "Status:" not in result.description

    def test_omits_priority_when_absent(self, zendesk_ticket_record):
        zendesk_ticket_record["priority"] = None
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert "Priority:" not in result.description

    @pytest.mark.parametrize(
        "missing_field",
        ["id", "subject", "description"],
    )
    def test_returns_none_when_required_field_missing(self, zendesk_ticket_record, missing_field):
        zendesk_ticket_record[missing_field] = None
        assert zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record) is None

    @pytest.mark.parametrize(
        "missing_field",
        ["id", "subject", "description"],
    )
    def test_returns_none_when_required_field_empty(self, zendesk_ticket_record, missing_field):
        zendesk_ticket_record[missing_field] = ""
        assert zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record) is None

    def test_returns_none_for_empty_record(self):
        assert zendesk_ticket_emitter(team_id=1, record={}) is None

    def test_extra_contains_only_meaningful_fields(self, zendesk_ticket_record):
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert set(result.extra.keys()) <= set(EXTRA_FIELDS)
        assert "description" not in result.extra
        assert "custom_fields" not in result.extra

    def test_extra_preserves_field_values(self, zendesk_ticket_record):
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert result.extra["id"] == 42
        assert result.extra["status"] == "open"
        assert result.extra["priority"] == "high"
        assert result.extra["brand_id"] == 1001


class TestZendeskTicketsConfig:
    def test_partition_field(self):
        assert ZENDESK_TICKETS_CONFIG.partition_field == "created_at"

    def test_where_clause_excludes_closed_and_solved(self):
        assert ZENDESK_TICKETS_CONFIG.where_clause is not None
        assert "closed" in ZENDESK_TICKETS_CONFIG.where_clause
        assert "solved" in ZENDESK_TICKETS_CONFIG.where_clause
        assert "NOT IN" in ZENDESK_TICKETS_CONFIG.where_clause

    def test_has_actionability_prompt(self):
        assert ZENDESK_TICKETS_CONFIG.actionability_prompt is not None
        assert "{description}" in ZENDESK_TICKETS_CONFIG.actionability_prompt

    def test_emitter_is_zendesk_ticket_emitter(self):
        assert ZENDESK_TICKETS_CONFIG.emitter is zendesk_ticket_emitter

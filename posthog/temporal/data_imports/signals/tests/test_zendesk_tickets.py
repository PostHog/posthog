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

    def test_description_contains_only_subject_and_body(self, zendesk_ticket_record):
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert result.description == f"{zendesk_ticket_record['subject']}\n{zendesk_ticket_record['description']}"

    @pytest.mark.parametrize("missing_field", ["id", "subject", "description"])
    def test_raises_when_required_field_falsy(self, zendesk_ticket_record, missing_field):
        zendesk_ticket_record[missing_field] = None
        with pytest.raises(ValueError, match="empty required field"):
            zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

    @pytest.mark.parametrize("missing_field", ["id", "subject", "description"])
    def test_raises_when_required_field_empty(self, zendesk_ticket_record, missing_field):
        zendesk_ticket_record[missing_field] = ""
        with pytest.raises(ValueError, match="empty required field"):
            zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

    def test_raises_for_empty_record(self):
        with pytest.raises(ValueError, match="missing required field"):
            zendesk_ticket_emitter(team_id=1, record={})

    def test_extra_contains_only_meaningful_fields(self, zendesk_ticket_record):
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert set(result.extra.keys()) <= set(EXTRA_FIELDS)
        assert "description" not in result.extra
        assert "custom_fields" not in result.extra

    def test_extra_preserves_field_values(self, zendesk_ticket_record):
        result = zendesk_ticket_emitter(team_id=1, record=zendesk_ticket_record)

        assert result is not None
        assert result.extra["brand_id"] == 1001
        assert result.extra["created_at"] == "2025-01-15 10:30:00-05:00"
        assert result.extra["url"] == "https://testcorp.zendesk.com/api/v2/tickets/42.json"


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

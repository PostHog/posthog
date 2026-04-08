import pytest

from posthog.temporal.data_imports.signals.conversations_tickets import EXTRA_FIELDS, conversations_ticket_emitter


class TestConversationsTicketEmitter:
    def test_emits_signal_with_tagged_messages(self, conversations_ticket_record):
        result = conversations_ticket_emitter(team_id=1, record=conversations_ticket_record)

        assert result is not None
        assert result.source_product == "conversations"
        assert result.source_type == "ticket"
        assert result.source_id == "550e8400-e29b-41d4-a716-446655440000"
        assert result.weight == 1.0
        assert "C: " in result.description
        assert "T: " in result.description
        for _author, content in conversations_ticket_record["messages"]:
            assert content in result.description

    def test_prepends_email_subject_as_title_line(self, conversations_ticket_record):
        conversations_ticket_record["email_subject"] = "Cannot export dashboard"
        result = conversations_ticket_emitter(team_id=1, record=conversations_ticket_record)

        assert result is not None
        lines = result.description.split("\n")
        assert lines[0] == "Cannot export dashboard"
        for _author, content in conversations_ticket_record["messages"]:
            assert content in result.description

    @pytest.mark.parametrize("messages", [[], None])
    def test_returns_none_without_messages(self, conversations_ticket_record, messages):
        if messages is None:
            del conversations_ticket_record["messages"]
        else:
            conversations_ticket_record["messages"] = messages
        assert conversations_ticket_emitter(team_id=1, record=conversations_ticket_record) is None

    def test_raises_when_id_missing(self, conversations_ticket_record):
        del conversations_ticket_record["id"]
        with pytest.raises(ValueError, match="missing required field"):
            conversations_ticket_emitter(team_id=1, record=conversations_ticket_record)

    @pytest.mark.parametrize("falsy_id", [None, ""])
    def test_raises_when_id_falsy(self, conversations_ticket_record, falsy_id):
        conversations_ticket_record["id"] = falsy_id
        with pytest.raises(ValueError, match="empty required field"):
            conversations_ticket_emitter(team_id=1, record=conversations_ticket_record)

    def test_extra_contains_metadata_fields(self, conversations_ticket_record):
        result = conversations_ticket_emitter(team_id=1, record=conversations_ticket_record)

        assert result is not None
        assert set(result.extra.keys()) <= set(EXTRA_FIELDS)
        assert result.extra["channel_source"] == "widget"
        assert result.extra["status"] == "open"
        assert result.extra["priority"] == "high"
        assert result.extra["ticket_number"] == 17

    def test_nullable_extra_fields(self, conversations_ticket_record):
        conversations_ticket_record["priority"] = None
        result = conversations_ticket_emitter(team_id=1, record=conversations_ticket_record)

        assert result is not None
        assert result.extra["priority"] is None

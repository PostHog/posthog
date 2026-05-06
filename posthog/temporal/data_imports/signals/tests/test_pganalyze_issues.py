import pytest

from posthog.temporal.data_imports.signals.pganalyze_issues import (
    EXTRA_FIELDS,
    PGANALYZE_ISSUES_CONFIG,
    pganalyze_issue_emitter,
)


class TestPgAnalyzeIssueEmitter:
    def test_emits_signal_for_valid_issue(self, pganalyze_issue_record):
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert result.source_product == "pganalyze"
        assert result.source_type == "issue"
        assert result.source_id == "issue_abc123"
        assert result.weight == 1.0
        assert "[warning]" in result.description
        assert "production-primary" in result.description
        assert "users_email_idx" in result.description
        assert "Index 'users_email_idx'" in result.description

    def test_description_contains_severity_server_and_body(self, pganalyze_issue_record):
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert pganalyze_issue_record["description"] in result.description

    @pytest.mark.parametrize("missing_field", ["id", "description"])
    def test_raises_when_required_field_falsy(self, pganalyze_issue_record, missing_field):
        pganalyze_issue_record[missing_field] = None
        with pytest.raises(ValueError, match="empty required field"):
            pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

    @pytest.mark.parametrize("missing_field", ["id", "description"])
    def test_raises_when_required_field_empty(self, pganalyze_issue_record, missing_field):
        pganalyze_issue_record[missing_field] = ""
        with pytest.raises(ValueError, match="empty required field"):
            pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

    def test_raises_for_empty_record(self):
        with pytest.raises(ValueError, match="missing required field"):
            pganalyze_issue_emitter(team_id=1, record={})

    def test_extra_contains_only_meaningful_fields(self, pganalyze_issue_record):
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert set(result.extra.keys()) <= set(EXTRA_FIELDS)
        assert "description" not in result.extra

    def test_references_parsed_from_json_string(self, pganalyze_issue_record):
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert isinstance(result.extra["references"], list)
        assert result.extra["references"][0]["name"] == "users_email_idx"

    def test_references_default_to_empty_list_when_none(self, pganalyze_issue_record):
        pganalyze_issue_record["references"] = None
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert result.extra["references"] == []

    def test_raises_on_malformed_references_json(self, pganalyze_issue_record):
        pganalyze_issue_record["references"] = "not-json"
        with pytest.raises(ValueError, match="not valid JSON"):
            pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

    def test_raises_on_non_array_references_json(self, pganalyze_issue_record):
        pganalyze_issue_record["references"] = '{"not": "an array"}'
        with pytest.raises(ValueError, match="not a JSON array|not a list"):
            pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

    def test_falls_back_when_severity_missing(self, pganalyze_issue_record):
        pganalyze_issue_record["severity"] = None
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert "[unknown]" in result.description

    def test_falls_back_when_server_name_missing(self, pganalyze_issue_record):
        pganalyze_issue_record["server_name"] = None
        result = pganalyze_issue_emitter(team_id=1, record=pganalyze_issue_record)

        assert result is not None
        assert "prod-1" in result.description


class TestPgAnalyzeIssuesConfig:
    def test_partition_field(self):
        assert PGANALYZE_ISSUES_CONFIG.partition_field == "synced_at"

    def test_has_actionability_prompt(self):
        assert PGANALYZE_ISSUES_CONFIG.actionability_prompt is not None
        assert "{description}" in PGANALYZE_ISSUES_CONFIG.actionability_prompt

    def test_has_summarization_prompt(self):
        assert PGANALYZE_ISSUES_CONFIG.summarization_prompt is not None
        assert "{description}" in PGANALYZE_ISSUES_CONFIG.summarization_prompt
        assert "{max_length}" in PGANALYZE_ISSUES_CONFIG.summarization_prompt

    def test_emitter_is_pganalyze_issue_emitter(self):
        assert PGANALYZE_ISSUES_CONFIG.emitter is pganalyze_issue_emitter

    def test_source_product_and_type(self):
        assert PGANALYZE_ISSUES_CONFIG.source_product == "pganalyze"
        assert PGANALYZE_ISSUES_CONFIG.source_type == "issue"

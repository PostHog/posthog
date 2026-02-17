import pytest

from posthog.temporal.data_imports.signals.github_issues import EXTRA_FIELDS, GITHUB_ISSUES_CONFIG, github_issue_emitter


class TestGithubIssueEmitter:
    def test_emits_signal_for_valid_issue(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert result.source_type == "github_issue"
        assert result.source_id == "12345"
        assert result.weight == 1.0
        assert "Charts fail to render" in result.description
        assert "special characters" in result.description

    def test_includes_body_in_description(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert "Description:" in result.description
        assert "blank white area" in result.description

    def test_includes_state_in_description(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert "State: open." in result.description

    def test_omits_body_when_absent(self, github_issue_record):
        github_issue_record["body"] = None
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert "Description:" not in result.description
        assert "Charts fail to render" in result.description

    def test_omits_body_when_empty(self, github_issue_record):
        github_issue_record["body"] = ""
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert "Description:" not in result.description

    def test_omits_state_when_absent(self, github_issue_record):
        github_issue_record["state"] = None
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert "State:" not in result.description

    @pytest.mark.parametrize("missing_field", ["id", "title"])
    def test_returns_none_when_required_field_missing(self, github_issue_record, missing_field):
        github_issue_record[missing_field] = None
        assert github_issue_emitter(team_id=1, record=github_issue_record) is None

    @pytest.mark.parametrize("missing_field", ["id", "title"])
    def test_returns_none_when_required_field_empty(self, github_issue_record, missing_field):
        github_issue_record[missing_field] = ""
        assert github_issue_emitter(team_id=1, record=github_issue_record) is None

    def test_returns_none_for_empty_record(self):
        assert github_issue_emitter(team_id=1, record={}) is None

    def test_extra_contains_only_expected_fields(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert set(result.extra.keys()) <= set(EXTRA_FIELDS)
        assert "body" not in result.extra
        assert "title" not in result.extra

    def test_extra_preserves_field_values(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert result.extra["html_url"] == "https://github.com/acme/analytics/issues/87"
        assert result.extra["number"] == 87
        assert result.extra["comments"] == 3


class TestGithubIssuesConfig:
    def test_partition_field(self):
        assert GITHUB_ISSUES_CONFIG.partition_field == "created_at"

    def test_where_clause_excludes_closed(self):
        assert GITHUB_ISSUES_CONFIG.where_clause is not None
        assert "closed" in GITHUB_ISSUES_CONFIG.where_clause
        assert "NOT IN" in GITHUB_ISSUES_CONFIG.where_clause

    def test_has_actionability_prompt(self):
        assert GITHUB_ISSUES_CONFIG.actionability_prompt is not None
        assert "{description}" in GITHUB_ISSUES_CONFIG.actionability_prompt

    def test_emitter_is_github_issue_emitter(self):
        assert GITHUB_ISSUES_CONFIG.emitter is github_issue_emitter

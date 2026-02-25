import pytest

from posthog.temporal.data_imports.signals.github_issues import EXTRA_FIELDS, GITHUB_ISSUES_CONFIG, github_issue_emitter


class TestGithubIssueEmitter:
    def test_emits_signal_for_valid_issue(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert result.source_product == "github"
        assert result.source_type == "issue"
        assert result.source_id == "12345"
        assert result.weight == 1.0
        assert "Charts fail to render" in result.description
        assert "special characters" in result.description

    def test_includes_body_in_description(self, github_issue_record):
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is not None
        assert "blank white area" in result.description

    @pytest.mark.parametrize("body", [None, ""])
    def test_skips_issue_with_no_body(self, github_issue_record, body):
        github_issue_record["body"] = body
        result = github_issue_emitter(team_id=1, record=github_issue_record)

        assert result is None

    @pytest.mark.parametrize("missing_field", ["id", "title"])
    def test_raises_when_required_field_falsy(self, github_issue_record, missing_field):
        github_issue_record[missing_field] = None
        with pytest.raises(ValueError, match="empty required field"):
            github_issue_emitter(team_id=1, record=github_issue_record)

    @pytest.mark.parametrize("missing_field", ["id", "title"])
    def test_raises_when_required_field_empty(self, github_issue_record, missing_field):
        github_issue_record[missing_field] = ""
        with pytest.raises(ValueError, match="empty required field"):
            github_issue_emitter(team_id=1, record=github_issue_record)

    def test_raises_for_empty_record(self):
        with pytest.raises(ValueError, match="missing required field"):
            github_issue_emitter(team_id=1, record={})

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

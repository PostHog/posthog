import pytest

from posthog.temporal.data_imports.signals.linear_issues import EXTRA_FIELDS, linear_issue_emitter


class TestLinearIssueEmitter:
    def test_emits_signal_for_valid_issue(self, linear_issue_record):
        result = linear_issue_emitter(team_id=1, record=linear_issue_record)

        assert result is not None
        assert result.source_product == "linear"
        assert result.source_type == "issue"
        assert result.source_id == "abc-123-def"
        assert result.weight == 1.0
        assert "Dashboard widgets fail to load" in result.description
        assert "parsing error" in result.description

    @pytest.mark.parametrize("description", [None, ""])
    def test_skips_issue_with_no_description(self, linear_issue_record, description):
        linear_issue_record["description"] = description

        assert linear_issue_emitter(team_id=1, record=linear_issue_record) is None

    @pytest.mark.parametrize(
        "field,value",
        [("id", None), ("id", ""), ("title", None), ("title", "")],
    )
    def test_raises_when_required_field_falsy(self, linear_issue_record, field, value):
        linear_issue_record[field] = value
        with pytest.raises(ValueError, match="empty required field"):
            linear_issue_emitter(team_id=1, record=linear_issue_record)

    def test_raises_for_missing_fields(self):
        with pytest.raises(ValueError, match="missing required field"):
            linear_issue_emitter(team_id=1, record={})

    def test_extra_excludes_description_fields(self, linear_issue_record):
        result = linear_issue_emitter(team_id=1, record=linear_issue_record)

        assert result is not None
        assert set(result.extra.keys()) <= set(EXTRA_FIELDS)
        assert "description" not in result.extra
        assert "title" not in result.extra

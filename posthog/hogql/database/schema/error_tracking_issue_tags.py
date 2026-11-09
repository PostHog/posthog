from posthog.hogql.database.models import (
    BooleanDatabaseField,
    FieldOrTable,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    UUIDDatabaseField,
)


class RawErrorTrackingIssueTagsTable(Table):
    description: str = (
        "Versioned answers to error tracking issue tag questions, one row for each write of a tag on an issue. "
        "The row with the highest `version` for a (team_id, key, issue_id) is the current answer. "
        "Read it with `argMax(tuple(value), version).1`, because a bare `argMax` skips null answers."
    )
    fields: dict[str, FieldOrTable] = {
        "team_id": IntegerDatabaseField(name="team_id", nullable=False),
        "issue_id": UUIDDatabaseField(name="issue_id", nullable=False, description="The error tracking issue."),
        "key": StringDatabaseField(name="key", nullable=False, description="The key of the tag definition."),
        "value": BooleanDatabaseField(
            name="value", nullable=True, description="The answer: yes, no, or null when the tagger is unsure."
        ),
        "is_deleted": BooleanDatabaseField(
            name="is_deleted", nullable=False, description="Whether this version removes the answer."
        ),
        "version": IntegerDatabaseField(
            name="version", nullable=False, description="Monotonic version; the latest version is the current answer."
        ),
    }

    def to_printed_clickhouse(self, context):
        return "error_tracking_issue_tags"

    def to_printed_hogql(self):
        return "raw_error_tracking_issue_tags"

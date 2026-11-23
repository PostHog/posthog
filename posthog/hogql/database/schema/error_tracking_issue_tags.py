from typing import Optional

from posthog.hogql import ast
from posthog.hogql.base import Expr
from posthog.hogql.context import HogQLContext
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

    def get_predicates(self, context: Optional[HogQLContext] = None) -> list[Expr]:
        # A rule's rows show which issues matched its filter, so they are hidden wherever its label is hidden.
        if context is None or context.team_id is None or not context.restricted_properties:
            return []
        # Deferred because the facade loads Django models, and this module loads before Django does.
        from products.error_tracking.backend.facade.api import readable_issue_tag_keys  # noqa: PLC0415

        keys = readable_issue_tag_keys(context.team_id, context.restricted_properties)
        if keys is None:
            return []
        return [
            ast.CompareOperation(
                op=ast.CompareOperationOp.In,
                left=ast.Field(chain=["key"]),
                right=ast.Constant(value=sorted(keys)),
            )
        ]

    def to_printed_clickhouse(self, context):
        return "error_tracking_issue_tags"

    def to_printed_hogql(self):
        return "raw_error_tracking_issue_tags"

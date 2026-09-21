from typing import Optional

from posthog.hogql import ast
from posthog.hogql.base import Expr
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.models import DANGEROUS_NoTeamIdCheckTable
from posthog.hogql.database.postgres_table import PostgresTable
from posthog.hogql.parser import parse_expr


class TaggedItemsTable(PostgresTable, DANGEROUS_NoTeamIdCheckTable):
    """`posthog_taggeditem` rows that tag one kind of object, read through the generic pointer.

    The table has no `team_id`, so each instance passes a predicate that scopes the object id
    through a team-guarded system table. The object id lives in `object_uuid` or `object_id`,
    which other models share, so rows are also limited to the content type of `tagged_model`.
    Content type ids differ per deployment, so the id is resolved when the query is built.
    """

    tagged_model: str
    """The tagged model, named by its legacy foreign key on TaggedItem, for example `ticket`."""

    def get_predicates(self, context: Optional[HogQLContext] = None) -> list[Expr]:
        # Resolved here because this module is imported before Django loads its models.
        from posthog.models.tagged_item_registry import content_type_id_for_legacy_field  # noqa: PLC0415

        content_type_id = content_type_id_for_legacy_field(self.tagged_model)
        return [
            *super().get_predicates(context),
            parse_expr("content_type_id = {content_type_id}", {"content_type_id": ast.Constant(value=content_type_id)}),
        ]

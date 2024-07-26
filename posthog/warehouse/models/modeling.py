from django.contrib.postgres import fields as pg_fields
from django.contrib.postgres import indexes as pg_indexes
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy

from posthog.models.team import Team
from posthog.models.utils import (
    CreatedMetaFields,
    DeletedMetaFields,
    UpdatedMetaFields,
    UUIDModel,
)

LabelPath = list[str]


class LabelTreeField(models.Field):
    description = "A PostgreSQL label tree field provided by the ltree extension"

    def db_type(self, connection):
        return "ltree"

    def from_db_value(self, value, expression, connection) -> None | LabelPath:
        if value is None:
            return value

        return value.split(".")

    def to_python(self, value) -> None | LabelPath:
        if value is None:
            return value

        if isinstance(value, list):
            return value

        return value.split(".")

    def get_prep_value(self, value: LabelPath) -> str:
        return ".".join(value)


class LabelQuery(models.Lookup):
    lookup_name = "lquery"

    def __init__(self, *args, **kwargs):
        self.prepare_rhs = False
        super().__init__(*args, **kwargs)

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        params = lhs_params + rhs_params
        return "%s ~ %s" % (lhs, rhs), params


LabelTreeField.register_lookup(LabelQuery)


class DataWarehouseModel(CreatedMetaFields, UpdatedMetaFields, UUIDModel, DeletedMetaFields):
    class Meta:
        indexes = [
            models.Index(fields=("team_id", "name"), name="model_team_id_name"),
        ]

    class Materialization(models.TextChoices):
        TABLE = "Table"
        VIEW = "View"
        INCREMENTAL = "Incremental"

    name: models.CharField = models.CharField(max_length=128)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

    materialization: models.CharField = models.CharField(
        max_length=128, choices=Materialization.choices, default=Materialization.VIEW
    )
    incremental_key = pg_fields.ArrayField(models.CharField(null=False), null=True, blank=True)
    unique_key = pg_fields.ArrayField(models.CharField(null=False), null=True, blank=True)
    query: models.JSONField = models.JSONField(default=dict, help_text="HogQL query")

    def clean(self) -> None:
        """Clean this model by running validation methods."""
        super().clean()
        self.validate_key_fields_in_query()

    def hogql_query(self) -> "ast.SelectQuery":
        from posthog.hogql.context import HogQLContext
        from posthog.hogql.parser import parse_select
        from posthog.hogql.printer import prepare_ast_for_printing
        from posthog.hogql.query import create_default_modifiers_for_team

        context = HogQLContext(
            team_id=self.team.pk,
            enable_select_queries=True,
            modifiers=create_default_modifiers_for_team(self.team),
        )
        parsed_query = parse_select(self.query["query"])
        select_query = prepare_ast_for_printing(
            parsed_query,
            context=context,
            dialect="hogql",
        )
        return select_query

    def validate_key_fields_in_query(self) -> None:
        """Validate `incremental_key` and `unique_key` are present in this model's query."""
        select_query = self.hogql_query()

        fields_set = set(select_query.select)
        incremental_key_set = set(self.incremental_key or [])
        unique_key_set = set(self.unique_key or [])

        incremental_key_error = {}
        if missing_incremental_keys := (incremental_key_set - fields_set):
            incremental_key_error = {
                "incremental_key": gettext_lazy(
                    f"The following incremental key fields are not present in the query: {','.join(missing_incremental_keys)}"
                )
            }

        unique_key_error = {}
        if missing_unique_keys := (unique_key_set - fields_set):
            unique_key_error = {
                "unique_key": gettext_lazy(
                    f"The following unique key fields are not present in the query: {','.join(missing_unique_keys)}"
                )
            }

        if incremental_key_error or unique_key_error:
            raise ValidationError({**incremental_key_error, **unique_key_error})


class DataWarehouseModelPath(CreatedMetaFields, UpdatedMetaFields, UUIDModel, DeletedMetaFields):
    class Meta:
        indexes = [
            models.Index(fields=("team_id", "path"), name="model_path_team_id_path"),
            pg_indexes.GistIndex("path", name="model_path_path"),
        ]
        constraints = [models.UniqueConstraint(fields=("team_id", "path"), name="unique_team_id_path")]

    path = LabelTreeField(null=False)
    team: models.ForeignKey = models.ForeignKey(Team, on_delete=models.CASCADE)

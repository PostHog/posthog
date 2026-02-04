"""
Auto-generate HogQL table definitions from Django models for PostgreSQL queries.

This module provides a DjangoTable class and utilities to automatically generate
HogQL table definitions from Django models that are subject to access control.
These tables are used exclusively with the postgres dialect for AI agent queries.
"""

from typing import TYPE_CHECKING, Optional

from django.db import models

from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateDatabaseField,
    DateTimeDatabaseField,
    FieldOrTable,
    FloatDatabaseField,
    IntegerDatabaseField,
    StringDatabaseField,
    StringJSONDatabaseField,
    Table,
    UUIDDatabaseField,
)

from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES, model_to_resource
from posthog.scopes import APIScopeObject

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext


class DjangoTable(Table):
    """
    A HogQL Table representing a Django model for PostgreSQL queries.

    This table type is used to identify tables that should have access control
    guards applied during query compilation.
    """

    # The Django model's actual database table name
    _db_table: str
    # The HogQL-friendly name for the table
    _hogql_name: str
    # The resource type for access control (e.g., "dashboard", "insight")
    resource: Optional[APIScopeObject]
    # Whether the model has a created_by field for creator bypass
    has_created_by: bool

    def __init__(
        self,
        *,
        fields: dict[str, FieldOrTable],
        db_table: str,
        hogql_name: str,
        resource: Optional[APIScopeObject] = None,
        has_created_by: bool = False,
    ):
        super().__init__(fields=fields)
        self._db_table = db_table
        self._hogql_name = hogql_name
        self.resource = resource
        self.has_created_by = has_created_by

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        # For PostgreSQL, we return the actual database table name
        return self._db_table

    def to_printed_hogql(self) -> str:
        return self._hogql_name


def django_field_to_hogql(field: models.Field) -> Optional[FieldOrTable]:
    """Convert a Django model field to a HogQL database field."""
    field_name = field.column if hasattr(field, "column") else field.name
    nullable = field.null if hasattr(field, "null") else True

    if isinstance(field, models.AutoField | models.BigAutoField | models.IntegerField | models.BigIntegerField):
        return IntegerDatabaseField(name=field_name, nullable=nullable)
    elif isinstance(field, models.FloatField | models.DecimalField):
        return FloatDatabaseField(name=field_name, nullable=nullable)
    elif isinstance(
        field, models.CharField | models.TextField | models.SlugField | models.EmailField | models.URLField
    ):
        return StringDatabaseField(name=field_name, nullable=nullable)
    elif isinstance(field, models.BooleanField | models.NullBooleanField):
        return BooleanDatabaseField(name=field_name, nullable=nullable)
    elif isinstance(field, models.DateTimeField):
        return DateTimeDatabaseField(name=field_name, nullable=nullable)
    elif isinstance(field, models.DateField):
        return DateDatabaseField(name=field_name, nullable=nullable)
    elif isinstance(field, models.UUIDField):
        return UUIDDatabaseField(name=field_name, nullable=nullable)
    elif isinstance(field, models.JSONField):
        return StringJSONDatabaseField(name=field_name, nullable=nullable)
    elif isinstance(field, models.ForeignKey):
        # For foreign keys, expose the _id column as an integer
        fk_column = f"{field.name}_id"
        return IntegerDatabaseField(name=fk_column, nullable=nullable)

    # Skip fields we don't know how to handle
    return None


def build_table_from_model(model: type[models.Model], resource: Optional[APIScopeObject] = None) -> DjangoTable:
    """
    Convert a Django model to a HogQL DjangoTable definition.

    Args:
        model: The Django model class
        resource: The resource type for access control

    Returns:
        A DjangoTable instance with fields mapped from the Django model
    """
    fields: dict[str, FieldOrTable] = {}

    for field in model._meta.get_fields():
        # Skip reverse relations and many-to-many fields
        if isinstance(field, models.ManyToOneRel | models.ManyToManyRel | models.ManyToManyField):
            continue

        hogql_field = django_field_to_hogql(field)
        if hogql_field:
            # Use the field name for HogQL access
            field_name = field.name
            if isinstance(field, models.ForeignKey):
                field_name = f"{field.name}_id"
            fields[field_name] = hogql_field

    # Determine model metadata
    db_table = model._meta.db_table
    # Create a HogQL-friendly name from the model name
    hogql_name = model._meta.model_name or model.__name__.lower()
    has_created_by = hasattr(model, "created_by") or "created_by_id" in [f.name for f in model._meta.get_fields()]

    return DjangoTable(
        fields=fields,
        db_table=db_table,
        hogql_name=hogql_name,
        resource=resource,
        has_created_by=has_created_by,
    )


# Cache for generated tables
_DJANGO_TABLES_CACHE: Optional[dict[str, DjangoTable]] = None


def get_django_tables() -> dict[str, DjangoTable]:
    """
    Auto-generate HogQL tables from Django models that have team_id and are access-controlled.

    Returns:
        A dictionary mapping HogQL table names to DjangoTable instances
    """
    global _DJANGO_TABLES_CACHE

    if _DJANGO_TABLES_CACHE is not None:
        return _DJANGO_TABLES_CACHE

    from django.apps import apps

    tables: dict[str, DjangoTable] = {}

    for model in apps.get_models():
        # Only include models with team field (team_id is the standard pattern)
        has_team = False
        for field in model._meta.get_fields():
            if isinstance(field, models.ForeignKey) and field.name == "team":
                has_team = True
                break
            if hasattr(field, "name") and field.name == "team_id":
                has_team = True
                break

        if not has_team:
            continue

        # Check if this model maps to a resource we care about
        resource = model_to_resource(model)
        if resource and resource in ACCESS_CONTROL_RESOURCES:
            table = build_table_from_model(model, resource)
            tables[table._hogql_name] = table

    _DJANGO_TABLES_CACHE = tables
    return tables


def clear_django_tables_cache():
    """Clear the cached Django tables. Used for testing."""
    global _DJANGO_TABLES_CACHE
    _DJANGO_TABLES_CACHE = None

"""
Internal HogQL wrapper around the `ee_accesscontrol` Postgres table.

This table is registered in the HogQL `Database` tree under a single fixed name
so the resolver can find it when printing object-level access-control predicates.

It is NOT exposed to users:

- Excluded from `get_posthog_table_names()` (hardcoded list).
- Excluded from `get_system_table_names()` (only iterates the `system.*` subtree).
- Direct user queries (`SELECT * FROM _posthog_internal_access_control`) are
  blocked by an explicit gate in `Database.get_table`. The printer flips the
  gate open only while resolving table-level predicates.

The exposed schema is the minimal column set needed to encode the RBAC
precedence rules in SQL — audit columns (`created_at`, `created_by`, etc.)
are deliberately omitted so the surface area stays small if the table ever
leaks into a user-facing surface.
"""

from posthog.hogql.database.models import IntegerDatabaseField, StringDatabaseField
from posthog.hogql.database.postgres_table import PostgresTable

# Single source of truth for the registration key. Any consumer that needs to
# build access-control predicates references this name.
INTERNAL_ACCESS_CONTROL_TABLE_NAME = "_posthog_internal_access_control"


def build_internal_access_control_table() -> PostgresTable:
    return PostgresTable(
        name=INTERNAL_ACCESS_CONTROL_TABLE_NAME,
        postgres_table_name="ee_accesscontrol",
        fields={
            # `team_id` is the tenant boundary; the printer auto-injects an
            # equality guard on it via `_ensure_team_id_where_clause`.
            "team_id": IntegerDatabaseField(name="team_id"),
            "resource": StringDatabaseField(name="resource"),
            "resource_id": StringDatabaseField(name="resource_id"),
            "access_level": StringDatabaseField(name="access_level"),
            # FK uuids — nullable; null+null = "default" row applying to all
            # members. The predicate logic disambiguates default vs. explicit.
            "organization_member_id": StringDatabaseField(name="organization_member_id"),
            "role_id": StringDatabaseField(name="role_id"),
        },
    )

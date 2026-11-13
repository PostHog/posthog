from django.db import migrations

# PostHog Review took the `code_review` identifier namespace. This migration only expands: every
# stored scope and access control row that names an old object gains a copy under the new name,
# and the old names stay. Pods still on the old code keep finding the old names during the deploy,
# and a refresh that intersects an old token with a new ceiling (or the reverse) keeps one name.
# A follow-up migration, in a separate PR after this deploys, removes the old names and old rows.
RENAMED_SCOPES = {
    "review_hog:read": "code_review:read",
    "review_hog:write": "code_review:write",
    "stamphog:read": "code_review_approval:read",
    "stamphog:write": "code_review_approval:write",
}
OLD_RESOURCE = "stamphog"
NEW_RESOURCE = "code_review_approval"

BATCH_SIZE = 5000

# (table, column) pairs that store scopes as an array.
SCOPE_ARRAY_COLUMNS = [
    ("posthog_personalapikey", "scopes"),
    ("posthog_projectsecretapikey", "scopes"),
    ("posthog_oauthapplication", "scopes"),
    ("posthog_oauthapplication", "optional_scopes"),
    ("posthog_workloadtrustpolicy", "scopes"),
    ("posthog_workloadtrustpolicyrequest", "scopes"),
]

# (table, column, extra filter) for columns that store scopes as one space-separated string.
# The access token filter matches the condition of `oauthaccesstoken_scopes_gin`, so each batch
# finds its rows through that index instead of scanning the table. Tokens without an application
# are minted inside PostHog and never carry these scopes.
SCOPE_TEXT_COLUMNS = [
    ("posthog_oauthaccesstoken", "scope", "AND application_id IS NOT NULL"),
    ("posthog_oauthgrant", "scope", ""),
    ("posthog_oauthdevicegrant", "scope", ""),
    ("posthog_oauthdevicegrant", "required_scope", ""),
]

# The unique constraint treats NULL columns as distinct, so ON CONFLICT alone would not stop a
# re-run from inserting a second copy. NOT EXISTS matches the target with NULLs as equal.
SAME_TARGET = """
    duplicate.team_id = original.team_id
    AND duplicate.resource_id IS NOT DISTINCT FROM original.resource_id
    AND duplicate.organization_member_id IS NOT DISTINCT FROM original.organization_member_id
    AND duplicate.role_id IS NOT DISTINCT FROM original.role_id
"""


def _update_in_batches(cursor, table: str, set_clause: str, where_clause: str) -> None:
    # Each batch commits on its own (the migration is not atomic), so no row lock outlives one batch.
    while True:
        cursor.execute(
            f"UPDATE {table} SET {set_clause} WHERE id IN (SELECT id FROM {table} WHERE {where_clause} LIMIT %s)",
            [BATCH_SIZE],
        )
        if cursor.rowcount < BATCH_SIZE:
            return


def _add_scope_next_to(cursor, present: str, added: str) -> None:
    """Append `added` to every stored scope list that holds `present` but not `added` yet."""
    for table, column in SCOPE_ARRAY_COLUMNS:
        _update_in_batches(
            cursor,
            table,
            f"{column} = array_append({column}, '{added}')",
            f"{column} @> ARRAY['{present}']::varchar[] AND NOT {column} @> ARRAY['{added}']::varchar[]",
        )
    for table, column, extra_filter in SCOPE_TEXT_COLUMNS:
        tokens = f"string_to_array({column}, ' ')"
        _update_in_batches(
            cursor,
            table,
            f"{column} = {column} || ' {added}'",
            f"{tokens} @> ARRAY['{present}'] AND NOT {tokens} @> ARRAY['{added}'] {extra_filter}",
        )


def _remove_scope(cursor, removed: str) -> None:
    for table, column in SCOPE_ARRAY_COLUMNS:
        _update_in_batches(
            cursor,
            table,
            f"{column} = array_remove({column}, '{removed}')",
            f"{column} @> ARRAY['{removed}']::varchar[]",
        )
    for table, column, extra_filter in SCOPE_TEXT_COLUMNS:
        tokens = f"string_to_array({column}, ' ')"
        _update_in_batches(
            cursor,
            table,
            f"{column} = array_to_string(array_remove({tokens}, '{removed}'), ' ')",
            f"{tokens} @> ARRAY['{removed}'] {extra_filter}",
        )


def _copy_access_rows(cursor, from_resource: str, to_resource: str) -> None:
    """Copy every access control row of `from_resource` to `to_resource`, unless the target already has one."""
    cursor.execute(
        f"""
        INSERT INTO ee_accesscontrol (
            id, access_level, resource, resource_id, created_at, updated_at,
            created_by_id, organization_member_id, role_id, team_id
        )
        SELECT
            gen_random_uuid(), original.access_level, '{to_resource}', original.resource_id, now(), now(),
            original.created_by_id, original.organization_member_id, original.role_id, original.team_id
        FROM ee_accesscontrol original
        WHERE original.resource = '{from_resource}'
            AND NOT EXISTS (
                SELECT 1 FROM ee_accesscontrol duplicate WHERE duplicate.resource = '{to_resource}' AND {SAME_TARGET}
            )
        ON CONFLICT DO NOTHING
        """
    )


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for old, new in RENAMED_SCOPES.items():
            _add_scope_next_to(cursor, present=old, added=new)
        _copy_access_rows(cursor, from_resource=OLD_RESOURCE, to_resource=NEW_RESOURCE)


def backwards(apps, schema_editor):
    # New code issues new names on their own (refreshed tokens, new keys, new access rows), so the
    # old name goes back on first. Only then are the new names removed, and old code keeps working.
    with schema_editor.connection.cursor() as cursor:
        for old, new in RENAMED_SCOPES.items():
            _add_scope_next_to(cursor, present=new, added=old)
            _remove_scope(cursor, new)
        _copy_access_rows(cursor, from_resource=NEW_RESOURCE, to_resource=OLD_RESOURCE)
        cursor.execute(f"DELETE FROM ee_accesscontrol WHERE resource = '{NEW_RESOURCE}'")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ee", "0070_squash_2026_11_02_schema_addons"),
        ("posthog", "1435_ema_issuer_management"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards, elidable=True),
    ]

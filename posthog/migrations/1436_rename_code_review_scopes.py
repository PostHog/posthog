from django.db import migrations

# PostHog Review took the `code_review` identifier namespace. Stored scope strings and access
# control rows still name the old objects, so this rewrites them to the new names.
RENAMED_SCOPES = {
    "review_hog:read": "code_review:read",
    "review_hog:write": "code_review:write",
    "stamphog:read": "code_review_approval:read",
    "stamphog:write": "code_review_approval:write",
}
RENAMED_RESOURCES = {"stamphog": "code_review_approval"}

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


def _replace_expression(column_expression: str, mapping: dict[str, str]) -> str:
    expression = column_expression
    for old, new in mapping.items():
        expression = f"array_replace({expression}, '{old}', '{new}')"
    return expression


def _update_in_batches(cursor, table: str, set_clause: str, where_clause: str) -> None:
    # Each batch commits on its own (the migration is not atomic), so no row lock outlives one batch.
    while True:
        cursor.execute(
            f"UPDATE {table} SET {set_clause} WHERE id IN (SELECT id FROM {table} WHERE {where_clause} LIMIT %s)",
            [BATCH_SIZE],
        )
        if cursor.rowcount < BATCH_SIZE:
            return


def _rename(schema_editor, scopes: dict[str, str], resources: dict[str, str]) -> None:
    old_scopes = ", ".join(f"'{old}'" for old in scopes)
    with schema_editor.connection.cursor() as cursor:
        for table, column in SCOPE_ARRAY_COLUMNS:
            _update_in_batches(
                cursor,
                table,
                f"{column} = {_replace_expression(column, scopes)}",
                f"{column} && ARRAY[{old_scopes}]::varchar[]",
            )
        for table, column, extra_filter in SCOPE_TEXT_COLUMNS:
            tokens = f"string_to_array({column}, ' ')"
            _update_in_batches(
                cursor,
                table,
                f"{column} = array_to_string({_replace_expression(tokens, scopes)}, ' ')",
                f"{tokens} && ARRAY[{old_scopes}]::text[] {extra_filter}",
            )
        for old, new in resources.items():
            _update_in_batches(cursor, "ee_accesscontrol", f"resource = '{new}'", f"resource = '{old}'")


def forwards(apps, schema_editor):
    _rename(schema_editor, RENAMED_SCOPES, RENAMED_RESOURCES)


def backwards(apps, schema_editor):
    _rename(
        schema_editor,
        {new: old for old, new in RENAMED_SCOPES.items()},
        {new: old for old, new in RENAMED_RESOURCES.items()},
    )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("ee", "0070_squash_2026_11_02_schema_addons"),
        ("posthog", "1435_ema_issuer_management"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards, elidable=True),
    ]

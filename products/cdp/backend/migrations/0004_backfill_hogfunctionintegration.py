from django.db import migrations

BATCH_SIZE = 1000


def _extract_integration_ids(inputs, inputs_schema):
    # Snapshot of products/cdp/backend/services/integration_usage.py extract_integration_ids —
    # migrations must stay self-contained as live code evolves.
    ids = set()
    inputs = inputs if isinstance(inputs, dict) else {}
    for schema in inputs_schema or []:
        if not isinstance(schema, dict) or schema.get("type") != "integration":
            continue
        entry = inputs.get(schema.get("key"))
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if isinstance(value, dict):
            value = value.get("integrationId")
        try:
            ids.add(int(str(value)))
        except (TypeError, ValueError):
            continue
    return ids


def backfill(apps, schema_editor):
    HogFunction = apps.get_model("cdp", "HogFunction")
    HogFunctionIntegration = apps.get_model("cdp", "HogFunctionIntegration")
    Integration = apps.get_model("posthog", "Integration")

    # (function_id, team_id) -> referenced integration ids; only functions with
    # integration-typed inputs are scanned, which keeps the pass small.
    pending: list[tuple] = []

    def flush():
        if not pending:
            return
        referenced_ids = {integration_id for _, _, ids in pending for integration_id in ids}
        # Only link integrations that exist in the function's team — job JSON is user-controlled.
        team_by_integration = dict(Integration.objects.filter(id__in=referenced_ids).values_list("id", "team_id"))
        rows = [
            HogFunctionIntegration(hog_function_id=function_id, integration_id=integration_id)
            for function_id, team_id, ids in pending
            for integration_id in ids
            if team_by_integration.get(integration_id) == team_id
        ]
        HogFunctionIntegration.objects.bulk_create(rows, batch_size=BATCH_SIZE, ignore_conflicts=True)
        pending.clear()

    functions = (
        HogFunction.objects.filter(deleted=False, inputs_schema__contains=[{"type": "integration"}])
        .values_list("id", "team_id", "inputs", "inputs_schema")
        .iterator(chunk_size=BATCH_SIZE)
    )
    for function_id, team_id, inputs, inputs_schema in functions:
        ids = _extract_integration_ids(inputs, inputs_schema)
        if ids:
            pending.append((function_id, team_id, ids))
        if len(pending) >= BATCH_SIZE:
            flush()
    flush()


def reverse(apps, schema_editor):
    apps.get_model("cdp", "HogFunctionIntegration").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("cdp", "0003_hogfunctionintegration"),
    ]

    operations = [
        migrations.RunPython(backfill, reverse),
    ]

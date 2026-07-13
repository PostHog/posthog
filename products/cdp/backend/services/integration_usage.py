from typing import Any

from django.db.models import Count

from posthog.models.integration import Integration

from products.cdp.backend.models import HogFunction
from products.cdp.backend.models.hog_functions.hog_function import HogFunctionIntegration


def _integration_id_from_input(input_entry: Any) -> int | None:
    if not isinstance(input_entry, dict):
        return None
    # Mirrors the runtime's resolution: input?.value?.integrationId ?? input?.value
    # (see nodejs/src/cdp/services/hog-inputs.service.ts loadIntegrationInputs)
    value = input_entry.get("value")
    if isinstance(value, dict):
        value = value.get("integrationId")
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def extract_integration_ids(inputs: Any, inputs_schema: Any) -> set[int]:
    """Integration IDs referenced by a hog function's integration-typed inputs.

    Only inputs declared as type "integration" in the inputs_schema are considered —
    that is the only surface the runtime resolves integrations from, so a matching ID
    planted anywhere else is not a reference.
    """
    ids: set[int] = set()
    inputs = inputs if isinstance(inputs, dict) else {}
    for schema in inputs_schema or []:
        if not isinstance(schema, dict) or schema.get("type") != "integration":
            continue
        integration_id = _integration_id_from_input(inputs.get(schema.get("key")))
        if integration_id is not None:
            ids.add(integration_id)
    return ids


def _function_references_integration(function: HogFunction, integration_id: int) -> bool:
    return integration_id in extract_integration_ids(function.inputs, function.inputs_schema)


def get_enabled_hog_functions_using_integration(team_id: int, integration_id: int) -> list[HogFunction]:
    """Enabled, non-deleted hog functions whose integration-typed inputs reference the integration."""
    functions = HogFunction.objects.filter(
        team_id=team_id,
        enabled=True,
        deleted=False,
        inputs_schema__contains=[{"type": "integration"}],
    ).only("id", "name", "inputs", "inputs_schema")
    return [function for function in functions if _function_references_integration(function, integration_id)]


def sync_hog_function_integrations(function: HogFunction) -> None:
    """Mirror the function's JSON integration references into HogFunctionIntegration rows.

    The JSON inputs stay the runtime source of truth; the join rows exist for cheap reverse
    lookups (usage counts, deletion guards). Only integrations that exist in the function's
    team are linked, so dangling or cross-team IDs in user-controlled JSON never create rows.
    Note: bulk_create/bulk_update writes bypass post_save and therefore this sync — rows
    catch up on the next regular save.
    """
    referenced_ids = extract_integration_ids(function.inputs, function.inputs_schema)
    desired_ids: set[int] = set()
    if referenced_ids:
        desired_ids = set(
            Integration.objects.filter(team_id=function.team_id, id__in=referenced_ids).values_list("id", flat=True)
        )
    existing_ids = set(
        HogFunctionIntegration.objects.filter(hog_function=function).values_list("integration_id", flat=True)
    )
    if removed_ids := existing_ids - desired_ids:
        HogFunctionIntegration.objects.filter(hog_function=function, integration_id__in=removed_ids).delete()
    if added_ids := desired_ids - existing_ids:
        HogFunctionIntegration.objects.bulk_create(
            [
                HogFunctionIntegration(hog_function=function, integration_id=integration_id)
                for integration_id in added_ids
            ],
            ignore_conflicts=True,
        )


def count_hog_functions_using_integrations(team_id: int, integration_ids: list[int]) -> dict[int, int]:
    """Number of non-deleted hog functions referencing each integration, keyed by integration ID."""
    if not integration_ids:
        return {}
    rows = (
        HogFunctionIntegration.objects.filter(
            integration_id__in=integration_ids,
            hog_function__team_id=team_id,
            hog_function__deleted=False,
        )
        .values("integration_id")
        .annotate(count=Count("id"))
    )
    return {row["integration_id"]: row["count"] for row in rows}

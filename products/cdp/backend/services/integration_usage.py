from typing import Any

from products.cdp.backend.models import HogFunction


def _input_references_integration(input_entry: Any, integration_id: int) -> bool:
    if not isinstance(input_entry, dict):
        return False
    # Mirrors the runtime's resolution: input?.value?.integrationId ?? input?.value
    # (see nodejs/src/cdp/services/hog-inputs.service.ts loadIntegrationInputs)
    value = input_entry.get("value")
    if isinstance(value, dict):
        value = value.get("integrationId")
    return value is not None and str(value) == str(integration_id)


def _function_references_integration(function: HogFunction, integration_id: int) -> bool:
    inputs = function.inputs if isinstance(function.inputs, dict) else {}
    for schema in function.inputs_schema or []:
        if not isinstance(schema, dict) or schema.get("type") != "integration":
            continue
        if _input_references_integration(inputs.get(schema.get("key")), integration_id):
            return True
    return False


def get_enabled_hog_functions_using_integration(team_id: int, integration_id: int) -> list[HogFunction]:
    """Enabled, non-deleted hog functions whose integration-typed inputs reference the integration.

    Only inputs declared as type "integration" in the function's inputs_schema are considered —
    that is the only surface the runtime resolves integrations from, so a matching ID planted
    anywhere else cannot block deletion.
    """
    functions = HogFunction.objects.filter(
        team_id=team_id,
        enabled=True,
        deleted=False,
        inputs_schema__contains=[{"type": "integration"}],
    ).only("id", "name", "inputs", "inputs_schema")
    return [function for function in functions if _function_references_integration(function, integration_id)]

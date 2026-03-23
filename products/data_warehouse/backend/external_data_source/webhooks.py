import dataclasses
from typing import Any

from django.conf import settings

from posthog.models import Team
from posthog.models.hog_function_template import HogFunctionTemplate
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.temporal.data_imports.sources.common.base import WebhookCreationResult, WebhookSource
from posthog.temporal.data_imports.sources.common.config import Config

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


@dataclasses.dataclass
class WebhookSetupResult:
    success: bool
    webhook_url: str = ""
    error: str | None = None


@dataclasses.dataclass
class WebhookHogFunctionCreateResult:
    hog_function: HogFunction | None = None
    webhook_url: str = ""
    error: str | None = None
    hog_function_created: bool = False


def get_or_create_webhook_hog_function(
    team: Team,
    source: WebhookSource,
    source_id: str,
    eligible_schemas: list[ExternalDataSchema],
    extra_inputs: dict[str, Any] | None = None,
) -> WebhookHogFunctionCreateResult:
    """Create or update a HogFunction for webhook-based data imports."""

    webhook_template = source.webhook_template
    if not webhook_template:
        return WebhookHogFunctionCreateResult(error="No webhook template available for this source")

    schema_mapping: dict[str, str] = {}
    object_type_map = source.webhook_resource_map

    for schema in eligible_schemas:
        schema_id_str = str(schema.id)

        object_type = object_type_map.get(schema.name)
        if object_type:
            schema_mapping[object_type] = schema_id_str

    db_template = HogFunctionTemplate.get_template(webhook_template.id)
    if not db_template:
        return WebhookHogFunctionCreateResult(
            error="Webhook template not found in database. Please run sync_hog_function_templates."
        )

    inputs: dict[str, Any] = {
        "schema_mapping": {"value": schema_mapping},
        "source_id": {"value": source_id},
    }
    if extra_inputs:
        inputs.update({key: {"value": value} for key, value in extra_inputs.items()})

    try:
        existing_hog = HogFunction.objects.get(
            team=team,
            type="warehouse_source_webhook",
            inputs__source_id__value=source_id,
        )
        if existing_hog.inputs:
            existing_mapping = existing_hog.inputs.get("schema_mapping", {}).get("value", {})
        else:
            existing_mapping = {}
    except HogFunction.DoesNotExist:
        existing_mapping = {}

    hog_function, created = HogFunction.objects.update_or_create(
        team=team,
        type="warehouse_source_webhook",
        inputs__source_id__value=source_id,
        defaults={
            "name": db_template.name,
            "description": db_template.description or "",
            "hog": db_template.code,
            "icon_url": db_template.icon_url,
            "enabled": True,
            "deleted": False,
            "template_id": db_template.template_id,
            "hog_function_template": db_template,
            "inputs_schema": db_template.inputs_schema,
            "inputs": inputs,
        },
    )

    # Merge with any existing schema_mapping from a previous call
    merged_mapping = {**existing_mapping, **schema_mapping}

    if merged_mapping != schema_mapping:
        hog_function.inputs = {
            **(hog_function.inputs or {}),
            "schema_mapping": {"value": merged_mapping},
        }
        hog_function.save(update_fields=["inputs", "encrypted_inputs"])

    webhooks_host = {
        "US": "https://webhooks.us.posthog.com",
        "EU": "https://webhooks.eu.posthog.com",
        "DEV": "https://app.dev.posthog.dev",
    }.get((settings.CLOUD_DEPLOYMENT or "").upper(), settings.SITE_URL)

    webhook_url = f"{webhooks_host}/public/webhooks/dwh/{hog_function.id}"

    return WebhookHogFunctionCreateResult(
        hog_function=hog_function, webhook_url=webhook_url, hog_function_created=created
    )


def create_and_register_webhook(
    source: WebhookSource,
    config: Config,
    hog_fn_result: WebhookHogFunctionCreateResult,
    team_id: int,
) -> WebhookSetupResult:
    """Create the external webhook and save any extra inputs (e.g. signing secret) onto the HogFunction."""
    assert hog_fn_result.hog_function is not None

    result: WebhookCreationResult = source.create_webhook(config, hog_fn_result.webhook_url, team_id)

    if result.success and result.extra_inputs:
        hog_function = hog_fn_result.hog_function
        assert hog_function.inputs is not None
        hog_function.inputs = {
            **hog_function.inputs,
            **{key: {"value": value} for key, value in result.extra_inputs.items()},
        }
        hog_function.save(update_fields=["inputs", "encrypted_inputs"])

    return WebhookSetupResult(
        success=result.success,
        webhook_url=hog_fn_result.webhook_url,
        error=result.error,
    )

from typing import Any, Optional

from django.conf import settings
from django.core.management.base import BaseCommand

import dlt
import dlt.common
import dlt.common.configuration.resolve
from dlt.common.configuration.exceptions import LookupTrace, ValueNotSecretException
from dlt.common.configuration.providers.provider import ConfigProvider
from dlt.common.configuration.specs.base_configuration import is_secret_hint

from products.data_warehouse.backend.models.external_data_schema import ExternalDataSchema


# Redefine a broken DLT func
def _resolve_single_provider_value(
    provider: ConfigProvider,
    key: str,
    hint: type[Any],
    pipeline_name: str | None = None,
    config_section: str | None = None,
    explicit_sections: tuple[str, ...] = (),
    embedded_sections: tuple[str, ...] = (),
) -> tuple[Optional[Any], list[LookupTrace]]:
    traces: list[LookupTrace] = []

    if provider.supports_sections:
        ns = list(explicit_sections if explicit_sections is not None else ())  # This was the broken line
        # always extend with embedded sections
        ns.extend(embedded_sections)
    else:
        # if provider does not support sections and pipeline name is set then ignore it
        if pipeline_name:
            return None, traces
        else:
            # pass empty sections
            ns = []

    value = None
    while True:
        if config_section and provider.supports_sections:
            full_ns = ns.copy()
            # config section, is always present and innermost
            if config_section:
                full_ns.append(config_section)
        else:
            full_ns = ns
        value, ns_key = provider.get_value(key, hint, pipeline_name, *full_ns)
        # if secret is obtained from non secret provider, we must fail
        cant_hold_it: bool = not provider.supports_secrets and is_secret_hint(hint)
        if value is not None and cant_hold_it:
            raise ValueNotSecretException(provider.name, ns_key)

        # create trace, ignore providers that cant_hold_it
        if not cant_hold_it:
            traces.append(LookupTrace(provider.name, full_ns, ns_key, value))

        if value is not None:
            # value found, ignore further sections
            break
        if len(ns) == 0:
            # sections exhausted
            break
        # pop optional sections for less precise lookup
        ns.pop()

    return value, traces


dlt.common.configuration.resolve.resolve_single_provider_value = _resolve_single_provider_value


class Command(BaseCommand):
    help = "Sync Data Warehouse last incremental values from DLT S3"

    def handle(self, *args, **options):
        destination = dlt.destinations.filesystem(
            credentials={
                "aws_access_key_id": settings.AIRBYTE_BUCKET_KEY,
                "aws_secret_access_key": settings.AIRBYTE_BUCKET_SECRET,
                "region_name": settings.AIRBYTE_BUCKET_REGION,
                "AWS_DEFAULT_REGION": settings.AIRBYTE_BUCKET_REGION,
                "AWS_S3_ALLOW_UNSAFE_RENAME": "true",
            },
            bucket_url=str(settings.BUCKET_URL),
        )

        schemas = (
            ExternalDataSchema.objects.filter(sync_type="incremental", deleted=False)
            .exclude(sync_type_config__has_key="incremental_field_last_value")
            .select_related("source")
        )

        total_schemas = len(schemas)
        print(f"Total schemas: {total_schemas}")  # noqa: T201

        for index, schema in enumerate(schemas):
            print(f"Updating schema {index + 1}/{total_schemas} - Schema.ID: {schema.pk}")  # noqa: T201

            dataset_name = schema.folder_path()
            team_id = schema.team_id
            schema_id = str(schema.id)
            job_type = schema.source.source_type
            pipeline_name = f"{job_type}_pipeline_{team_id}_run_{schema_id}"

            pipeline = dlt.pipeline(
                pipeline_name=pipeline_name,
                destination=destination,
                dataset_name=dataset_name,
            )

            pipeline.sync_destination()

            try:
                sources = pipeline.state["sources"]
                resource = sources[next(iter(sources.keys()))]
                resources = resource["resources"]
                tables = resources[next(iter(resources.keys()))]
                table = tables[next(iter(tables.keys()))]
                incremental = table[next(iter(table.keys()))]
                last_incremental_value = incremental.get("last_value")
            except Exception as e:
                print(f"Cant get last_incremental_value for schema: {schema.pk}. ERROR: {e}")  # noqa: T201
                pipeline.drop()
                continue

            try:
                schema.update_incremental_field_value(last_incremental_value)
            except Exception as e:
                print(  # noqa: T201
                    f"Cant update_incremental_field_value for schema: {schema.pk}. With last_incremental_value={last_incremental_value}. ERROR: {e}"
                )
                pipeline.drop()
                continue

            pipeline.drop()

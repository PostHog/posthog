from typing import Any

from structlog.types import FilteringBoundLogger

from posthog.temporal.data_imports.pipelines.pipeline.typings import SourceResponse


def stackadapt_ads_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any | None = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    raise NotImplementedError("StackAdapt data fetching not yet implemented")


def validate_credentials(api_token: str) -> bool:
    raise NotImplementedError("StackAdapt credential validation not yet implemented")

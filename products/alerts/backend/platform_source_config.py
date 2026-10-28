"""Where the alerts platform finds the schema of an insight alert's `source_config`.

Registered from `ready()`, so it stays light: the schema loads on first use.
"""

from products.alerts_platform.backend.facade.contracts import SourceConfigSpec


def load_insight_source_config() -> SourceConfigSpec:
    from products.alerts.backend.platform_source_config_schema import (  # noqa: PLC0415 - keeps posthog.schema off the startup path
        INSIGHT_SOURCE_CONFIG,
    )

    return INSIGHT_SOURCE_CONFIG

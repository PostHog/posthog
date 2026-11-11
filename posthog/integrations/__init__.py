"""The integrations SDK: the only way to read and write `Integration` rows. See README.md and AGENTS.md.

from posthog.integrations import IntegrationManager, IntegrationNotFound, IntegrationRecord
from posthog.integrations.fields import IntegrationReferenceField
"""

import importlib
from typing import TYPE_CHECKING, Any

from posthog.integrations.contracts import (
    SOURCE_MARKER_CONFIG_KEY,
    ConfigValue,
    CrossTeamFilter,
    IntegrationConflict,
    IntegrationInUse,
    IntegrationNotFound,
    IntegrationPatch,
    IntegrationRecord,
    IntegrationUsage,
    KindSpec,
    RepositoryCache,
    UnknownIntegrationKind,
    UnsupportedAuthType,
    UnsupportedIntegrationFilter,
    UpdatedRows,
)
from posthog.integrations.enums import AuthType, IntegrationAuthType
from posthog.integrations.references import IntegrationReference
from posthog.integrations.secret_reads import UndecryptedIntegrationSecretError

if TYPE_CHECKING:
    from posthog.integrations.kinds_generated import IntegrationKind
    from posthog.integrations.manager import (
        AuthAccessor,
        IntegrationManager,
        IntegrationReader,
        OAuthAccessor,
        SourceKindAccessor,
        UsageProvider,
        register_source_kinds,
        register_usage_provider,
    )

# Loaded on first use (PEP 562). The model module imports the catalogue from this package, and
# importing a submodule runs this file first, so an eager import of the accessors (which import
# the model) would be a circular import.
_LAZY_NAMES = {
    "IntegrationKind": "posthog.integrations.kinds_generated",
    **dict.fromkeys(
        (
            "AuthAccessor",
            "IntegrationManager",
            "IntegrationReader",
            "OAuthAccessor",
            "SourceKindAccessor",
            "UsageProvider",
            "register_source_kinds",
            "register_usage_provider",
        ),
        "posthog.integrations.manager",
    ),
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_NAMES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(_LAZY_NAMES[name]), name)
    globals()[name] = value
    return value


__all__ = [
    "SOURCE_MARKER_CONFIG_KEY",
    "AuthAccessor",
    "AuthType",
    "ConfigValue",
    "CrossTeamFilter",
    "IntegrationAuthType",
    "IntegrationConflict",
    "IntegrationInUse",
    "IntegrationKind",
    "IntegrationManager",
    "IntegrationNotFound",
    "IntegrationPatch",
    "IntegrationReader",
    "IntegrationRecord",
    "IntegrationReference",
    "IntegrationUsage",
    "KindSpec",
    "OAuthAccessor",
    "RepositoryCache",
    "SourceKindAccessor",
    "UnknownIntegrationKind",
    "UnsupportedAuthType",
    "UndecryptedIntegrationSecretError",
    "UnsupportedIntegrationFilter",
    "UpdatedRows",
    "UsageProvider",
    "register_source_kinds",
    "register_usage_provider",
]

"""Bootstrap a local PostHog project from an S3 dump of the events and persons tables.

The dumps are produced by the PostHog S3 batch export feature (Parquet/JSONLines, optionally
compressed). See ``posthog/management/commands/bootstrap_local_project.py`` for the CLI entry point.
"""

from posthog.local_bootstrap.config import (
    BootstrapConfig,
    BootstrapConfigError,
    DiscoveredFile,
    S3Location,
    TableImportConfig,
    TablePlan,
    TableResult,
)
from posthog.local_bootstrap.importer import BootstrapReport, Progress, run_bootstrap
from posthog.local_bootstrap.source import iter_table_rows, list_files

__all__ = [
    "BootstrapConfig",
    "BootstrapConfigError",
    "BootstrapReport",
    "DiscoveredFile",
    "Progress",
    "S3Location",
    "TableImportConfig",
    "TablePlan",
    "TableResult",
    "iter_table_rows",
    "list_files",
    "run_bootstrap",
]

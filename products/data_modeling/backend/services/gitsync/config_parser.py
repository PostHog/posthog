"""Parse and serialize posthog.toml and dag.toml configuration files.

A posthog.toml file defines the root of a modeling project. A modeling project can contain multiple
teams / environments within it. So it is scoped at the "Organization" level.

    # AUTO GENERATED
    [project]
    name = "Acme Analytics"  # organization name
    version = 1

    [environments.production]  # populated on github integration creation from within a team context
    name = "production"

    [environments.staging]
    name = "staging"

    # USER CONFIGURABLE
    [settings]
    models_directory = "models"  # relative to repo root and user configurable

A dag.toml lives inside each directory which should denote a separate DAG within a team. It
configures DAG level settings like sync frequency. The optional name field overrides the
directory-derived DAG name.

    name = "Finance Pipeline"
    sync_frequency = "1h"
    description = "Core business metrics refreshed hourly"

An example repo layout with multiple environments and multiple DAGs is actually quite simple:

    posthog.toml
    models/
      production/
        finance/
          dag.toml
          finance_model_1.sql  # just an example name, relax
        marketing/
          dag.toml
          marketing_model_1.sql
      staging/
        ...
"""

import tomllib
from dataclasses import dataclass
from datetime import timedelta

import structlog

from products.data_warehouse.backend.models.external_data_schema import sync_frequency_to_sync_frequency_interval

logger = structlog.get_logger(__name__)

POSTHOG_TOML = "posthog.toml"
DAG_TOML = "dag.toml"
SUPPORTED_VERSIONS = (1,)

# map human-friendly duration strings to DataWarehouseSyncInterval values
_DURATION_TO_SYNC_INTERVAL: dict[str, str] = {
    "15m": "15min",
    "30m": "30min",
    "1h": "1hour",
    "6h": "6hour",
    "12h": "12hour",
    "24h": "24hour",
    "1d": "24hour",
    "7d": "7day",
    "30d": "30day",
}

DEFAULT_SYNC_FREQUENCY = "1d"


@dataclass
class EnvironmentConfig:
    """Configuration for a single environment."""

    name: str


@dataclass
class DAGConfig:
    """Parsed representation of a dag.toml file."""

    name: str = ""
    sync_frequency: str = DEFAULT_SYNC_FREQUENCY
    description: str = ""

    @property
    def sync_frequency_interval(self) -> timedelta | None:
        interval_key = _DURATION_TO_SYNC_INTERVAL.get(self.sync_frequency)
        if not interval_key:
            raise ValueError(f"Unknown sync_frequency: {self.sync_frequency!r}")
        return sync_frequency_to_sync_frequency_interval(interval_key)


@dataclass
class ProjectConfig:
    """Parsed representation of a posthog.toml file."""

    name: str
    version: int
    environments: list[EnvironmentConfig]
    models_directory: str = "models"

    @property
    def is_multi_environment(self) -> bool:
        return len(self.environments) > 1


def parse_project_config(content: str) -> ProjectConfig:
    """Parse a posthog.toml file into a ProjectConfig.

    Raises ValueError on:
    - Invalid TOML syntax
    - Unknown top-level sections
    - Missing required fields ([project] name)
    - Unsupported version
    - Both [environment] and [environments] present (mutually exclusive)
    - Invalid types for known fields
    """
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Invalid posthog.toml: {e}") from e

    unknown_sections = set(data.keys()) - _VALID_PROJECT_SECTIONS
    if unknown_sections:
        raise ValueError(f"Unknown sections in posthog.toml: {', '.join(sorted(unknown_sections))}")

    # [project] section is required
    project = data.get("project")
    if not project or not isinstance(project, dict):
        raise ValueError("posthog.toml must have a [project] section")

    name = project.get("name", "")
    if not name:
        raise ValueError("posthog.toml [project] must have a name")
    if not isinstance(name, str):
        raise ValueError(f"[project] name must be a string, got {type(name).__name__}")

    version = project.get("version", SUPPORTED_VERSIONS[-1])
    if not isinstance(version, int):
        raise ValueError(f"[project] version must be an integer, got {type(version).__name__}")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported posthog.toml version {version}, expected one of: {SUPPORTED_VERSIONS}")

    # [environment] and [environments] are mutually exclusive
    has_single = "environment" in data
    has_multi = "environments" in data
    if has_single and has_multi:
        raise ValueError("[environment] and [environments] are mutually exclusive -- use one or the other")

    environments: list[EnvironmentConfig] = []
    if has_multi:
        envs = data["environments"]
        if not isinstance(envs, dict):
            raise ValueError("[environments] must be a table of environment configs")
        for key, env_data in envs.items():
            if not isinstance(env_data, dict):
                raise ValueError(f"[environments.{key}] must be a table")
            env_name = env_data.get("name", key)
            environments.append(EnvironmentConfig(name=env_name))
    elif has_single:
        env = data["environment"]
        if not isinstance(env, dict):
            raise ValueError("[environment] must be a table")
        env_name = env.get("name", "production")
        environments.append(EnvironmentConfig(name=env_name))
    else:
        environments.append(EnvironmentConfig(name="production"))

    if not environments:
        raise ValueError("posthog.toml must define at least one environment")

    # Check for duplicate environment names
    env_names = [e.name for e in environments]
    duplicates = {n for n in env_names if env_names.count(n) > 1}
    if duplicates:
        raise ValueError(f"Duplicate environment names: {', '.join(sorted(duplicates))}")

    # [settings] section
    settings = data.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError("[settings] must be a table")
    models_directory = settings.get("models_directory", "models")
    if not isinstance(models_directory, str):
        raise ValueError(f"[settings] models_directory must be a string, got {type(models_directory).__name__}")

    return ProjectConfig(
        name=name,
        version=version,
        environments=environments,
        models_directory=models_directory,
    )


_VALID_DAG_KEYS = {"name", "sync_frequency", "description"}

_VALID_PROJECT_SECTIONS = {"project", "environment", "environments", "settings"}


def parse_dag_config(content: str) -> DAGConfig:
    """Parse a dag.toml file into a DAGConfig.

    Raises ValueError on:
    - Invalid TOML syntax
    - Unknown keys
    - Invalid sync_frequency value
    - Wrong types for known fields
    """
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Invalid dag.toml: {e}") from e

    unknown_keys = set(data.keys()) - _VALID_DAG_KEYS
    if unknown_keys:
        raise ValueError(f"Unknown keys in dag.toml: {', '.join(sorted(unknown_keys))}")

    name = data.get("name", "")
    sync_frequency = data.get("sync_frequency", DEFAULT_SYNC_FREQUENCY)
    description = data.get("description", "")

    if not isinstance(name, str):
        raise ValueError(f"name must be a string, got {type(name).__name__}")
    if not isinstance(sync_frequency, str):
        raise ValueError(f"sync_frequency must be a string, got {type(sync_frequency).__name__}")
    if not isinstance(description, str):
        raise ValueError(f"description must be a string, got {type(description).__name__}")

    if sync_frequency not in _DURATION_TO_SYNC_INTERVAL:
        valid = ", ".join(sorted(_DURATION_TO_SYNC_INTERVAL.keys()))
        raise ValueError(f"Invalid sync_frequency {sync_frequency!r}. Valid values: {valid}")

    return DAGConfig(
        name=name,
        sync_frequency=sync_frequency,
        description=description,
    )


def serialize_project_config(
    *,
    name: str,
    environments: list[str] | None = None,
    models_directory: str = "models",
) -> str:
    """Serialize a ProjectConfig to a posthog.toml string.

    Used when scaffolding a new repo during initial setup.
    """
    lines: list[str] = [
        "[project]",
        f'name = "{_escape_toml(name)}"',
        f"version = {SUPPORTED_VERSIONS[-1]}",
        "",
    ]
    if environments and len(environments) > 1:
        for env in environments:
            lines.append(f"[environments.{env}]")
            lines.append(f'name = "{_escape_toml(env)}"')
            lines.append("")
    else:
        env_name = environments[0] if environments else "production"
        lines.append("[environment]")
        lines.append(f'name = "{_escape_toml(env_name)}"')
        lines.append("")
    lines.append("[settings]")
    lines.append(f'models_directory = "{_escape_toml(models_directory)}"')
    lines.append("")

    return "\n".join(lines)


def serialize_dag_config(
    *,
    name: str = "",
    sync_frequency: str = DEFAULT_SYNC_FREQUENCY,
    description: str = "",
) -> str:
    """Serialize a DagConfig to a dag.toml string."""
    lines: list[str] = []
    if name:
        lines.append(f'name = "{_escape_toml(name)}"')
    if description:
        lines.append(f'description = "{_escape_toml(description)}"')
    lines.append(f'sync_frequency = "{_escape_toml(sync_frequency)}"')
    lines.append("")
    return "\n".join(lines)


def _escape_toml(value: str) -> str:
    """Escape special characters for a TOML basic string."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

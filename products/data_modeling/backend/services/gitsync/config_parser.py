"""Parse and serialize posthog and dag configuration files.

A posthog config file (posthog.toml / posthog.yaml / posthog.yml) defines the root of a modeling
project. A modeling project can contain multiple teams / environments within it. So it is scoped
at the "Organization" level.

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

The same shape in YAML:

    project:
      name: Acme Analytics
      version: 1
    environments:
      production:
        name: production
      staging:
        name: staging
    settings:
      models_directory: models

A dag config file (dag.toml / dag.yaml / dag.yml) lives inside each directory which should denote
a separate DAG within a team. It configures DAG level settings like sync frequency. The optional
name field overrides the directory-derived DAG name.

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

import re
import tomllib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import yaml
import structlog

from products.data_warehouse.backend.models.external_data_schema import sync_frequency_to_sync_frequency_interval

logger = structlog.get_logger(__name__)

POSTHOG_CONFIG_BASENAMES = ("posthog.toml", "posthog.yaml", "posthog.yml")
DAG_CONFIG_BASENAMES = ("dag.toml", "dag.yaml", "dag.yml")
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


class ConfigFormat(ABC):
    """Strategy for serializing/deserializing configuration files.

    Subclasses must declare the file extensions they own and implement loads/dumps. All formats
    must round-trip through a plain dict so that downstream validation stays format-agnostic.
    """

    extensions: tuple[str, ...] = ()
    label: str = ""

    @abstractmethod
    def loads(self, content: str) -> dict[str, Any]: ...

    @abstractmethod
    def dumps(self, data: dict[str, Any]) -> str: ...


class TomlFormat(ConfigFormat):
    extensions = (".toml",)
    label = "toml"

    def loads(self, content: str) -> dict[str, Any]:
        try:
            return tomllib.loads(content)
        except tomllib.TOMLDecodeError as e:
            raise ValueError(str(e)) from e

    def dumps(self, data: dict[str, Any]) -> str:
        return _toml_dumps(data)


class YamlFormat(ConfigFormat):
    extensions = (".yaml", ".yml")
    label = "yaml"

    def loads(self, content: str) -> dict[str, Any]:
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise ValueError(str(e)) from e
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError(f"top-level value must be a mapping, got {type(data).__name__}")
        return data

    def dumps(self, data: dict[str, Any]) -> str:
        return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


_FORMATS: tuple[ConfigFormat, ...] = (TomlFormat(), YamlFormat())
_DEFAULT_FORMAT: ConfigFormat = _FORMATS[0]


def format_for_path(path: str) -> ConfigFormat:
    """Pick a ConfigFormat from a file path's extension. Raises ValueError on unknown extensions."""
    lowered = path.lower()
    for fmt in _FORMATS:
        for ext in fmt.extensions:
            if lowered.endswith(ext):
                return fmt
    raise ValueError(f"Unsupported config file extension: {path!r}")


@dataclass
class EnvironmentConfig:
    """Configuration for a single environment."""

    name: str


@dataclass
class DAGConfig:
    """Parsed representation of a dag config file."""

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
    """Parsed representation of a posthog config file."""

    name: str
    version: int
    environments: list[EnvironmentConfig]
    models_directory: str = "models"

    @property
    def is_multi_environment(self) -> bool:
        return len(self.environments) > 1


_VALID_PROJECT_SECTIONS = {"project", "environment", "environments", "settings"}
_VALID_DAG_KEYS = {"name", "sync_frequency", "description"}


def parse_project_config(content: str, format: ConfigFormat | None = None) -> ProjectConfig:
    """Parse a posthog config file (TOML or YAML) into a ProjectConfig.

    Raises ValueError on:
    - Invalid syntax
    - Unknown top-level sections
    - Missing required fields ([project] name)
    - Unsupported version
    - Both [environment] and [environments] present (mutually exclusive)
    - Invalid types for known fields
    """
    fmt = format or _DEFAULT_FORMAT
    try:
        data = fmt.loads(content)
    except ValueError as e:
        raise ValueError(f"Invalid posthog config: {e}") from e

    unknown_sections = set(data.keys()) - _VALID_PROJECT_SECTIONS
    if unknown_sections:
        raise ValueError(f"Unknown sections in posthog config: {', '.join(sorted(unknown_sections))}")

    # [project] section is required
    project = data.get("project")
    if not project or not isinstance(project, dict):
        raise ValueError("posthog config must have a [project] section")

    name = project.get("name", "")
    if not name:
        raise ValueError("posthog config [project] must have a name")
    if not isinstance(name, str):
        raise ValueError(f"[project] name must be a string, got {type(name).__name__}")

    version = project.get("version", SUPPORTED_VERSIONS[-1])
    if not isinstance(version, int):
        raise ValueError(f"[project] version must be an integer, got {type(version).__name__}")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported posthog config version {version}, expected one of: {SUPPORTED_VERSIONS}")

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
            if not isinstance(env_name, str):
                raise ValueError(f"[environments.{key}] name must be a string, got {type(env_name).__name__}")
            environments.append(EnvironmentConfig(name=env_name))
    elif has_single:
        env = data["environment"]
        if not isinstance(env, dict):
            raise ValueError("[environment] must be a table")
        env_name = env.get("name", "production")
        if not isinstance(env_name, str):
            raise ValueError(f"[environment] name must be a string, got {type(env_name).__name__}")
        environments.append(EnvironmentConfig(name=env_name))
    else:
        environments.append(EnvironmentConfig(name="production"))

    if not environments:
        raise ValueError("posthog config must define at least one environment")

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


def parse_dag_config(content: str, format: ConfigFormat | None = None) -> DAGConfig:
    """Parse a dag config file (TOML or YAML) into a DAGConfig.

    Raises ValueError on:
    - Invalid syntax
    - Unknown keys
    - Invalid sync_frequency value
    - Wrong types for known fields
    """
    fmt = format or _DEFAULT_FORMAT
    try:
        data = fmt.loads(content)
    except ValueError as e:
        raise ValueError(f"Invalid dag config: {e}") from e

    unknown_keys = set(data.keys()) - _VALID_DAG_KEYS
    if unknown_keys:
        raise ValueError(f"Unknown keys in dag config: {', '.join(sorted(unknown_keys))}")

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
    format: ConfigFormat | None = None,
) -> str:
    """Serialize a ProjectConfig to the target format. Used when scaffolding a new repo."""
    fmt = format or _DEFAULT_FORMAT
    data: dict[str, Any] = {
        "project": {
            "name": name,
            "version": SUPPORTED_VERSIONS[-1],
        },
    }
    if environments and len(environments) > 1:
        data["environments"] = {_slugify(env): {"name": env} for env in environments}
    else:
        env_name = environments[0] if environments else "production"
        data["environment"] = {"name": env_name}
    data["settings"] = {"models_directory": models_directory}
    return fmt.dumps(data)


def serialize_dag_config(
    *,
    name: str = "",
    sync_frequency: str = DEFAULT_SYNC_FREQUENCY,
    description: str = "",
    format: ConfigFormat | None = None,
) -> str:
    """Serialize a DAGConfig to the target format."""
    fmt = format or _DEFAULT_FORMAT
    data: dict[str, Any] = {}
    if name:
        data["name"] = name
    if description:
        data["description"] = description
    data["sync_frequency"] = sync_frequency
    return fmt.dumps(data)


def _slugify(value: str) -> str:
    """Normalize a string to a lowercase kebab-case bare key."""
    from django.utils.text import slugify

    value = slugify(value).replace("_", "-")
    return re.sub(r"-+", "-", value)


def _toml_dumps(data: dict[str, Any]) -> str:
    """Minimal TOML serializer for the shapes this module emits.

    Handles top-level scalar keys, single-level [tables], and nested [tables.subtables].
    Not a general-purpose serializer.
    """
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    for k, v in scalars.items():
        lines.append(f"{k} = {_toml_value(v)}")
    if scalars and tables:
        lines.append("")
    for i, (table_name, table) in enumerate(tables.items()):
        if i > 0:
            lines.append("")
        nested_tables = {k: v for k, v in table.items() if isinstance(v, dict)}
        flat = {k: v for k, v in table.items() if not isinstance(v, dict)}
        if nested_tables and not flat:
            for j, (sub_name, sub) in enumerate(nested_tables.items()):
                if j > 0:
                    lines.append("")
                lines.append(f"[{table_name}.{sub_name}]")
                for k, v in sub.items():
                    lines.append(f"{k} = {_toml_value(v)}")
        else:
            lines.append(f"[{table_name}]")
            for k, v in flat.items():
                lines.append(f"{k} = {_toml_value(v)}")
    lines.append("")
    return "\n".join(lines)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return f'"{_escape_toml(value)}"'
    raise ValueError(f"Unsupported TOML value type: {type(value).__name__}")


def _escape_toml(value: str) -> str:
    """Escape special characters for a TOML basic string."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

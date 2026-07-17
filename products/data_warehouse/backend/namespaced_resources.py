"""Registry for sources whose schema rows are namespaced by an external resource set.

GitHub is the current example: its tables are namespaced per repository, the repo list lives in
``job_inputs``, and editing it adds/retires schema rows and reconciles per-repo webhooks. Like the
direct-query engine registry, the presentation layer dispatches through this registry keyed on the
source type (resolved here, never named inline) so it stays source-agnostic. The reconciliation
touches ``DataWarehouseTable`` / schema rows, so it is data_warehouse-domain and lives here.
"""

from abc import ABC, abstractmethod
from typing import Any

from products.data_warehouse.backend.github_warehouse_repos import (
    github_repositories_for_job_inputs,
    reconcile_github_repositories,
)
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType


class NamespacedResourceAdapter(ABC):
    """How a namespaced-resource source syncs its schema rows to an external resource set."""

    # These sources keep the legacy resource's rows bare alongside qualified rows for the others
    # (GitHub: the legacy repo stays unqualified), so bare<->qualified tail matching would wrongly
    # collapse them. Match schema names exactly instead.
    uses_strict_schema_name_match: bool = True

    @abstractmethod
    def resources_for_job_inputs(self, job_inputs: dict[str, Any] | None) -> list[str]:
        """The effective resource list encoded in stored ``job_inputs``."""
        raise NotImplementedError()

    @abstractmethod
    def reconcile_resources(
        self, *, source_model: Any, team: Any, old_resources: list[str], new_config: Any
    ) -> None:
        """Bring schema rows and per-resource webhooks in line with the persisted new resource list."""
        raise NotImplementedError()

    def schema_metadata_by_name(self, schemas: list[Any]) -> dict[str, Any] | None:
        """Per-resource location metadata to seed on newly created schema rows."""
        return {schema.name: schema.schema_metadata for schema in schemas if schema.schema_metadata}


class _GithubNamespacedResources(NamespacedResourceAdapter):
    def resources_for_job_inputs(self, job_inputs):
        return github_repositories_for_job_inputs(job_inputs)

    def reconcile_resources(self, *, source_model, team, old_resources, new_config):
        reconcile_github_repositories(
            source_model=source_model, team=team, old_repositories=old_resources, new_config=new_config
        )


_ADAPTERS: dict[str, NamespacedResourceAdapter] = {
    ExternalDataSourceType.GITHUB: _GithubNamespacedResources(),
}


def get_namespaced_resource_adapter(source_type: str) -> NamespacedResourceAdapter | None:
    """Adapter for a namespaced-resource source, or None for sources without namespaced schemas."""
    return _ADAPTERS.get(source_type)

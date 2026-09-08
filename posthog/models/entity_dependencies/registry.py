from abc import ABC, abstractmethod
from typing import Any, Generic, Literal, TypeVar

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete, post_save

import structlog
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.models.entity_dependencies.sync import plan_sync, remove_dependencies, sync_dependencies
from posthog.models.entity_dependencies.types import EntityRef, EntityRefStatus, Reference, SyncResult

logger = structlog.get_logger(__name__)

ENTITY_DEPENDENCY_SYNC_FAILURES = Counter(
    "entity_dependency_sync_failures_total",
    "Signal-driven dependency syncs that failed and left stale rows behind",
    labelnames=["source_type", "operation"],
)

M = TypeVar("M", bound=models.Model)


class EntityDependencyRegistryError(Exception):
    pass


class DependencySource(ABC, Generic[M]):
    """Describes how instances of one model reference other entities.

    A product implements this for a model that holds references, then calls `register_source()`
    once at app-ready time. Core never imports product models: the registry is keyed by
    `entity_type`, a stable string that survives a model moving between apps.

    `extract_references` must be a pure function of the instance. Return an empty list for an
    instance the product considers gone (soft-deleted, archived): the diff in `sync_dependencies`
    then removes its rows, and a later restore recreates them.
    """

    entity_type: str
    model: type[M]

    @abstractmethod
    def extract_references(self, instance: M) -> list[Reference]: ...

    def get_queryset(self) -> models.QuerySet[M]:
        """Every instance a backfill must visit. Cross-team by design, so fail-closed managers are unscoped."""
        manager = self.model._default_manager
        unscoped = getattr(manager, "unscoped", None)
        if callable(unscoped):
            return unscoped()
        return manager.all()


class DependencyResolver(ABC):
    """Resolves ids of one entity type into displayable references.

    A product implements this for a model that dependency rows point at (as target or source),
    then calls `register_resolver()` at app-ready time. `resolve` must batch: one call resolves
    every id the read API needs for that type, so it should run one query, not one per id.

    Ids absent from the returned dict are reported as `missing` by `resolve_references`, so a
    resolver only returns entities that exist for the team (soft-deleted ones included, with
    `status="deleted"`, because a dangling reference to a restorable entity is not the same as
    one to an entity that is gone).
    """

    entity_type: str

    @abstractmethod
    def resolve(self, team_id: int, ids: list[str]) -> dict[str, EntityRef]: ...


_sources_by_type: dict[str, DependencySource[Any]] = {}
_sources_by_model: dict[type[models.Model], DependencySource[Any]] = {}
_resolvers_by_type: dict[str, DependencyResolver] = {}


def register_source(source: DependencySource[Any]) -> None:
    """Register a source and keep its rows current through `post_save` and `post_delete`."""
    existing = _sources_by_type.get(source.entity_type)
    if existing is not None and existing is not source:
        raise EntityDependencyRegistryError(
            f"Entity type {source.entity_type!r} is already registered by {type(existing).__name__}"
        )
    existing_for_model = _sources_by_model.get(source.model)
    if existing_for_model is not None and existing_for_model is not source:
        raise EntityDependencyRegistryError(
            f"Model {source.model.__name__} is already registered as {existing_for_model.entity_type!r}"
        )

    _sources_by_type[source.entity_type] = source
    _sources_by_model[source.model] = source
    post_save.connect(_on_source_saved, sender=source.model, dispatch_uid=_dispatch_uid(source, "save"), weak=False)
    post_delete.connect(
        _on_source_deleted, sender=source.model, dispatch_uid=_dispatch_uid(source, "delete"), weak=False
    )


def unregister_source(entity_type: str) -> None:
    source = _sources_by_type.pop(entity_type, None)
    if source is None:
        return
    _sources_by_model.pop(source.model, None)
    post_save.disconnect(sender=source.model, dispatch_uid=_dispatch_uid(source, "save"))
    post_delete.disconnect(sender=source.model, dispatch_uid=_dispatch_uid(source, "delete"))


def register_resolver(resolver: DependencyResolver) -> None:
    existing = _resolvers_by_type.get(resolver.entity_type)
    if existing is not None and existing is not resolver:
        raise EntityDependencyRegistryError(
            f"Entity type {resolver.entity_type!r} already has resolver {type(existing).__name__}"
        )
    _resolvers_by_type[resolver.entity_type] = resolver


def unregister_resolver(entity_type: str) -> None:
    _resolvers_by_type.pop(entity_type, None)


def resolve_references(team_id: int, entity_type: str, ids: list[str]) -> dict[str, EntityRef]:
    """Resolve ids of one type into displayable references, with a ref for every requested id.

    Types without a registered resolver come back id-only with `status="unknown"`, so a read
    surface over a partially adopted registry degrades to showing ids instead of failing.
    """
    resolver = _resolvers_by_type.get(entity_type)
    if resolver is None:
        return {entity_id: EntityRef(type=entity_type, id=entity_id) for entity_id in ids}
    resolved = resolver.resolve(team_id, ids)
    return {
        entity_id: resolved.get(entity_id, EntityRef(type=entity_type, id=entity_id, status=EntityRefStatus.MISSING))
        for entity_id in ids
    }


def get_source(entity_type: str) -> DependencySource[Any]:
    try:
        return _sources_by_type[entity_type]
    except KeyError:
        raise EntityDependencyRegistryError(f"No dependency source registered for {entity_type!r}") from None


def registered_source_types() -> list[str]:
    return sorted(_sources_by_type)


def sync_instance_dependencies(instance: models.Model) -> SyncResult:
    """Sync one instance of a registered source explicitly.

    Write paths that bypass `save()` (`.update()`, `bulk_update`, raw SQL) fire no signals and
    must call this themselves. Raises on failure, unlike the signal receivers.
    """
    source = _source_for_instance(instance)
    return sync_dependencies(
        team_id=_team_id_of(instance),
        source_type=source.entity_type,
        source_id=str(instance.pk),
        references=source.extract_references(instance),
    )


def plan_instance_dependencies(instance: models.Model) -> SyncResult:
    """Report what `sync_instance_dependencies` would change, without writing. Used by dry runs."""
    source = _source_for_instance(instance)
    return plan_sync(
        team_id=_team_id_of(instance),
        source_type=source.entity_type,
        source_id=str(instance.pk),
        references=source.extract_references(instance),
    )


def _on_source_saved(sender: type[models.Model], instance: models.Model, raw: bool = False, **kwargs: Any) -> None:
    if raw:
        return
    _run_guarded(sender, instance, "save")


def _on_source_deleted(sender: type[models.Model], instance: models.Model, **kwargs: Any) -> None:
    _run_guarded(sender, instance, "delete")


def _run_guarded(sender: type[models.Model], instance: models.Model, operation: Literal["save", "delete"]) -> None:
    source = _sources_by_model.get(sender)
    if source is None:
        return
    try:
        if operation == "save":
            sync_instance_dependencies(instance)
        else:
            remove_dependencies(
                team_id=_team_id_of(instance), source_type=source.entity_type, source_id=str(instance.pk)
            )
    except Exception as e:
        # The registry is derived data and must never block a product write. Stale rows are
        # repaired by an explicit resync; the failure is still reported so it does not go unseen.
        logger.warn(
            "entity_dependencies.sync_failed",
            source_type=source.entity_type,
            source_id=str(instance.pk),
            operation=operation,
            exception=e,
        )
        capture_exception(e)
        ENTITY_DEPENDENCY_SYNC_FAILURES.labels(source_type=source.entity_type, operation=operation).inc()
        if settings.TEST:
            raise


def _source_for_instance(instance: models.Model) -> DependencySource[Any]:
    source = _sources_by_model.get(type(instance))
    if source is None:
        raise EntityDependencyRegistryError(f"{type(instance).__name__} is not registered as a dependency source")
    return source


def _team_id_of(instance: models.Model) -> int:
    team_id = getattr(instance, "team_id", None)
    if team_id is None:
        raise EntityDependencyRegistryError(
            f"{type(instance).__name__} has no team_id; dependency sources must be team-scoped models"
        )
    return int(team_id)


def _dispatch_uid(source: DependencySource[Any], operation: str) -> str:
    return f"entity_dependencies:{source.entity_type}:{operation}"

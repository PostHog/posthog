import copy
import json
from collections.abc import Callable, Sequence
from time import sleep
from typing import Any, TypeVar
from uuid import UUID

from django.db import InterfaceError, OperationalError, connection, transaction

import structlog

from posthog.dataclasses import frozen
from posthog.event_usage import report_organization_action
from posthog.models.organization import Organization

logger = structlog.get_logger(__name__)

UsagePatch = tuple[list[str], Any]
T = TypeVar("T")


def retry_quota_database_operation(operation: Callable[[], T]) -> T:
    for attempt in range(2):
        try:
            return operation()
        except (OperationalError, InterfaceError):
            # Keep a caller-owned transaction open, but replace a lost autocommit connection.
            if not connection.in_atomic_block:
                connection.close()
            logger.warning("quota_limiting_database_retry", attempt=attempt + 1)
            sleep(0.1 * 2**attempt)
    return operation()


def _resource_patch(operations: Sequence[UsagePatch]) -> dict[str, dict[str, Any]]:
    """Folds [resource, key] operations into one set map and one delete list for each resource.

    The last operation on a key wins.
    """
    patch: dict[str, dict[str, Any]] = {}
    for (resource, key), value in operations:
        entry = patch.setdefault(resource, {"set": {}, "delete": []})
        if value is None:
            entry["set"].pop(key, None)
            if key not in entry["delete"]:
                entry["delete"].append(key)
        else:
            entry["set"][key] = value
            if key in entry["delete"]:
                entry["delete"].remove(key)
    return patch


@frozen
class _QuotaAction:
    organization: Organization
    event: str
    properties: dict[str, Any] | None
    group_properties: dict[str, Any] | None

    def report(self) -> None:
        report_organization_action(self.organization, self.event, self.properties, self.group_properties)


class QuotaUsageBatch:
    def __init__(self) -> None:
        self._patches: dict[UUID, list[UsagePatch]] = {}
        self._usage_md5: dict[UUID, str] = {}
        self._actions: dict[UUID, list[_QuotaAction]] = {}

    def patch(self, organization: Organization, operations: Sequence[UsagePatch]) -> None:
        if any(len(path) != 2 for path, _ in operations):
            raise ValueError("QuotaUsageBatch patches only [resource, key] paths")
        self._patches.setdefault(organization.id, []).extend(operations)

    def require_unchanged_usage(self, organization: Organization, usage_md5: str) -> None:
        # The decision read this usage. A different value at write time means the decision is stale.
        self._usage_md5[organization.id] = usage_md5

    def report_action(
        self,
        organization: Organization,
        event: str,
        properties: dict[str, Any] | None = None,
        group_properties: dict[str, Any] | None = None,
    ) -> None:
        # Quota decisions mutate usage after reporting it, so deferred events need a snapshot.
        self._actions.setdefault(organization.id, []).append(
            _QuotaAction(
                organization=organization,
                event=event,
                properties=copy.deepcopy(properties),
                group_properties=copy.deepcopy(group_properties),
            )
        )

    def discard(self, organization: Organization) -> None:
        self._patches.pop(organization.id, None)
        self._usage_md5.pop(organization.id, None)
        self._actions.pop(organization.id, None)

    def write(self) -> set[UUID]:
        """Writes the patches and returns the organizations skipped because their usage changed."""
        skipped = retry_quota_database_operation(self._write)
        for org_id in skipped:
            self._actions.pop(org_id, None)
        self._patches.clear()
        self._usage_md5.clear()
        return skipped

    def publish(self) -> None:
        actions = [action for org_actions in self._actions.values() for action in org_actions]
        self._actions.clear()
        for action in actions:
            transaction.on_commit(action.report)

    def _write(self) -> set[UUID]:
        rows = [
            (org_id, self._usage_md5.get(org_id), _resource_patch(operations))
            for org_id, operations in self._patches.items()
            if operations
        ]
        if not rows:
            return set()

        # Skip a resource the row lacks instead of creating a partial resource object without its limit and usage.
        sql = (
            f"UPDATE {Organization._meta.db_table} AS o SET usage = o.usage || coalesce(("
            "SELECT jsonb_object_agg(r.key, ((o.usage -> r.key) || (r.value -> 'set')) "
            "- ARRAY(SELECT jsonb_array_elements_text(r.value -> 'delete'))) "
            "FROM jsonb_each(v.patch) AS r WHERE jsonb_typeof(o.usage -> r.key) = 'object'"
            "), '{}'::jsonb) "
            "FROM UNNEST(%s::uuid[], %s::text[], %s::jsonb[]) AS v(id, usage_md5, patch) "
            "WHERE o.id = v.id AND (v.usage_md5 IS NULL OR md5(o.usage::text) = v.usage_md5) "
            "RETURNING o.id"
        )
        parameters: list[Any] = [
            [org_id for org_id, _, _ in rows],
            [usage_md5 for _, usage_md5, _ in rows],
            [json.dumps(patch) for _, _, patch in rows],
        ]
        with connection.cursor() as cursor:
            # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (identifiers come from model metadata and fixed templates; resources, keys and values are parameters)
            cursor.execute(sql, parameters)
            written = {row[0] for row in cursor.fetchall()}
        return {org_id for org_id, usage_md5, _ in rows if usage_md5 is not None and org_id not in written}

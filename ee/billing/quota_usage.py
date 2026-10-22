import copy
import json
from collections import defaultdict
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
_PatchRow = tuple[UUID, str | None, list[Any]]
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
        groups: dict[tuple[tuple[tuple[str, ...], bool], ...], list[_PatchRow]] = defaultdict(list)
        for org_id, operations in self._patches.items():
            if operations:
                shape = tuple((tuple(path), value is None) for path, value in operations)
                values = [value for _, value in operations if value is not None]
                groups[shape].append((org_id, self._usage_md5.get(org_id), values))

        skipped: set[UUID] = set()
        if not groups:
            return skipped

        # Each shape can need a separate statement; all of an organization's patches commit together.
        with transaction.atomic():
            for shape, rows in groups.items():
                expression = "o.usage"
                parameters: list[Any] = []
                value_index = 0
                for path, delete in shape:
                    if delete:
                        expression = f"({expression}) #- %s::text[]"
                    else:
                        expression = f"jsonb_set({expression}, %s::text[], v.v{value_index})"
                        value_index += 1
                    parameters.append(list(path))

                array_sql = "%s::uuid[], %s::text[]" + ", %s::jsonb[]" * value_index
                parameters.append([org_id for org_id, _, _ in rows])
                parameters.append([usage_md5 for _, usage_md5, _ in rows])
                parameters.extend([json.dumps(values[index]) for _, _, values in rows] for index in range(value_index))
                columns = ", ".join(["id", "usage_md5", *(f"v{i}" for i in range(value_index))])
                table = Organization._meta.db_table
                sql = (
                    f"UPDATE {table} AS o SET usage = {expression} "
                    f"FROM UNNEST({array_sql}) AS v({columns}) "
                    "WHERE o.id = v.id AND (v.usage_md5 IS NULL OR md5(o.usage::text) = v.usage_md5) "
                    "RETURNING o.id"
                )
                with connection.cursor() as cursor:
                    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (identifiers come from model metadata and fixed templates; paths and values are parameters)
                    cursor.execute(sql, parameters)
                    written = {row[0] for row in cursor.fetchall()}
                skipped.update(
                    org_id for org_id, usage_md5, _ in rows if usage_md5 is not None and org_id not in written
                )
        return skipped

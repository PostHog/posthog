import json
import datetime
from dataclasses import dataclass
from typing import Optional, Union
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import DatabaseError
from django.utils.timezone import now

import structlog
from dateutil.parser import isoparse

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_GROUPS
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.group import Group
from posthog.models.group.sql import INSERT_GROUP_SQL
from posthog.personhog_client.metrics import PERSONHOG_ROUTING_ERRORS_TOTAL, PERSONHOG_ROUTING_TOTAL, get_client_name

logger = structlog.get_logger(__name__)


def raw_create_group_ch(
    team_id: int,
    group_type_index: GroupTypeIndex,
    group_key: str,
    properties: dict,
    created_at: datetime.datetime,
    timestamp: Optional[datetime.datetime] = None,
):
    """Create ClickHouse-only Group record.

    DON'T USE DIRECTLY - `create_group` is the correct option,
    unless you specifically want to sync Postgres state from ClickHouse yourself."""
    if timestamp is None:
        timestamp = now().astimezone(ZoneInfo("UTC"))
    data = {
        "group_type_index": group_type_index,
        "group_key": group_key,
        "team_id": team_id,
        "group_properties": json.dumps(properties),
        "created_at": created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "_timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }
    p = ClickhouseProducer()
    p.produce(topic=KAFKA_GROUPS, sql=INSERT_GROUP_SQL, data=data)


def create_group(
    team_id: int,
    group_type_index: GroupTypeIndex,
    group_key: str,
    properties: Optional[dict] = None,
    timestamp: Optional[Union[datetime.datetime, str]] = None,
) -> Group:
    """Create proper Group record (ClickHouse + Postgres)."""
    if not properties:
        properties = {}
    if not timestamp:
        timestamp = now()

    # clickhouse specific formatting
    if isinstance(timestamp, str):
        timestamp = isoparse(timestamp)
    else:
        timestamp = timestamp.astimezone(ZoneInfo("UTC"))

    raw_create_group_ch(
        team_id,
        group_type_index,
        group_key,
        properties,
        timestamp,
        timestamp=timestamp,
    )

    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.converters import proto_group_to_model
    from posthog.personhog_client.proto import CreateGroupRequest

    client = get_personhog_client()
    if client is not None:
        try:
            resp = client.create_group(
                CreateGroupRequest(
                    team_id=team_id,
                    group_type_index=group_type_index,
                    group_key=group_key,
                    group_properties=json.dumps(properties).encode(),
                    created_at=int(timestamp.timestamp() * 1000),
                )
            )
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="create_group", source="personhog", client_name=get_client_name()
            ).inc()
            return proto_group_to_model(resp.group)
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="create_group",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning(
                "personhog_create_group_failure",
                team_id=team_id,
                group_type_index=group_type_index,
                group_key=group_key,
                exc_info=True,
            )

    PERSONHOG_ROUTING_TOTAL.labels(operation="create_group", source="django_orm", client_name=get_client_name()).inc()
    group = Group.objects.create(  # nosemgrep: no-direct-persons-db-orm
        team_id=team_id,
        group_type_index=group_type_index,
        group_key=group_key,
        group_properties=properties,
        created_at=timestamp,
        version=0,
    )
    return group


def save_group(group: Group, *, operation: str = "group_save") -> None:
    """Save a Group's group_properties via personhog, falling back to ORM.

    Only group_properties is synced on the personhog path. The ORM fallback
    calls group.save() which persists all fields, but once the fallback is
    removed this will only write group_properties.
    """
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.proto import UpdateGroupRequest

    client = get_personhog_client()
    if client is not None:
        try:
            client.update_group(
                UpdateGroupRequest(
                    team_id=group.team_id,
                    group_type_index=group.group_type_index,
                    group_key=group.group_key,
                    update_mask=["group_properties"],
                    group_properties=json.dumps(group.group_properties).encode(),
                )
            )
            PERSONHOG_ROUTING_TOTAL.labels(operation=operation, source="personhog", client_name=get_client_name()).inc()
            return
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation=operation,
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning(
                "personhog_save_group_failure",
                team_id=group.team_id,
                group_type_index=group.group_type_index,
                group_key=group.group_key,
                exc_info=True,
            )

    PERSONHOG_ROUTING_TOTAL.labels(operation=operation, source="django_orm", client_name=get_client_name()).inc()
    group.save()


def get_group_by_key(team_id: int, group_type_index: int, group_key: str) -> Group | None:
    """Fetch a single Group via personhog, falling back to ORM on error."""
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.converters import proto_group_to_model
    from posthog.personhog_client.proto import GetGroupRequest

    client = get_personhog_client()
    if client is not None:
        try:
            resp = client.get_group(
                GetGroupRequest(team_id=team_id, group_type_index=group_type_index, group_key=group_key)
            )
            if resp.group and resp.group.id:
                PERSONHOG_ROUTING_TOTAL.labels(
                    operation="get_group_by_key", source="personhog", client_name=get_client_name()
                ).inc()
                return proto_group_to_model(resp.group)
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="get_group_by_key", source="personhog", client_name=get_client_name()
            ).inc()
            return None
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="get_group_by_key",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning(
                "personhog_get_group_by_key_failure",
                team_id=team_id,
                group_type_index=group_type_index,
                group_key=group_key,
                exc_info=True,
            )

    PERSONHOG_ROUTING_TOTAL.labels(
        operation="get_group_by_key", source="django_orm", client_name=get_client_name()
    ).inc()
    try:
        return Group.objects.get(  # nosemgrep: no-direct-persons-db-orm
            team_id=team_id, group_type_index=group_type_index, group_key=group_key
        )
    except Group.DoesNotExist:
        return None
    except DatabaseError:
        logger.warning(
            "persons_db_get_group_by_key_failure",
            team_id=team_id,
            group_type_index=group_type_index,
            group_key=group_key,
            exc_info=True,
        )
        return None


def get_groups_by_identifiers(team_id: int, group_type_index: int, group_keys: list[str]) -> list[Group]:
    """Fetch multiple Groups via personhog, falling back to ORM on error."""
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.converters import proto_group_to_model
    from posthog.personhog_client.proto import GetGroupsRequest, GroupIdentifier

    if not group_keys:
        return []

    client = get_personhog_client()
    if client is not None:
        try:
            groups: list[Group] = []
            for i in range(0, len(group_keys), settings.PERSONHOG_BATCH_SIZE):
                identifiers = [
                    GroupIdentifier(group_type_index=group_type_index, group_key=key)
                    for key in group_keys[i : i + settings.PERSONHOG_BATCH_SIZE]
                ]
                resp = client.get_groups(GetGroupsRequest(team_id=team_id, group_identifiers=identifiers))
                groups.extend(proto_group_to_model(g) for g in resp.groups if g.id)
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="get_groups_by_identifiers", source="personhog", client_name=get_client_name()
            ).inc()
            return groups
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="get_groups_by_identifiers",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning(
                "personhog_get_groups_by_identifiers_failure",
                team_id=team_id,
                group_type_index=group_type_index,
                exc_info=True,
            )

    PERSONHOG_ROUTING_TOTAL.labels(
        operation="get_groups_by_identifiers", source="django_orm", client_name=get_client_name()
    ).inc()
    try:
        return list(
            Group.objects.filter(  # nosemgrep: no-direct-persons-db-orm
                team_id=team_id, group_type_index=group_type_index, group_key__in=group_keys
            )
        )
    except DatabaseError:
        logger.warning(
            "persons_db_get_groups_by_identifiers_failure",
            team_id=team_id,
            group_type_index=group_type_index,
            exc_info=True,
        )
        return []


def get_groups_by_type_indices(team_id: int, group_type_indices: set[int], group_keys: set[str]) -> list[Group]:
    """Fetch Groups across multiple group type indices in a single call.

    Creates a GroupIdentifier for each (group_type_index, group_key) combination
    and fetches them all in one gRPC/ORM call."""
    from posthog.personhog_client.client import get_personhog_client
    from posthog.personhog_client.converters import proto_group_to_model
    from posthog.personhog_client.proto import GetGroupsRequest, GroupIdentifier

    if not group_type_indices or not group_keys:
        return []

    client = get_personhog_client()
    if client is not None:
        try:
            identifiers = [
                GroupIdentifier(group_type_index=gti, group_key=key) for gti in group_type_indices for key in group_keys
            ]
            groups: list[Group] = []
            for i in range(0, len(identifiers), settings.PERSONHOG_BATCH_SIZE):
                resp = client.get_groups(
                    GetGroupsRequest(
                        team_id=team_id, group_identifiers=identifiers[i : i + settings.PERSONHOG_BATCH_SIZE]
                    )
                )
                groups.extend(proto_group_to_model(g) for g in resp.groups if g.id)
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="get_groups_by_type_indices", source="personhog", client_name=get_client_name()
            ).inc()
            return groups
        except Exception:
            PERSONHOG_ROUTING_ERRORS_TOTAL.labels(
                operation="get_groups_by_type_indices",
                source="personhog",
                error_type="grpc_error",
                client_name=get_client_name(),
            ).inc()
            logger.warning(
                "personhog_get_groups_by_type_indices_failure",
                team_id=team_id,
                group_type_indices=list(group_type_indices),
                exc_info=True,
            )

    PERSONHOG_ROUTING_TOTAL.labels(
        operation="get_groups_by_type_indices", source="django_orm", client_name=get_client_name()
    ).inc()
    try:
        return list(
            Group.objects.filter(  # nosemgrep: no-direct-persons-db-orm
                team_id=team_id, group_type_index__in=group_type_indices, group_key__in=group_keys
            )
        )
    except DatabaseError:
        logger.warning(
            "persons_db_get_groups_by_type_indices_failure",
            team_id=team_id,
            group_type_indices=list(group_type_indices),
            exc_info=True,
        )
        return []


def get_aggregation_target_field(
    aggregation_group_type_index: Optional[GroupTypeIndex],
    event_table_alias: str,
    default: str,
) -> str:
    if aggregation_group_type_index is not None:
        return f'{event_table_alias}."$group_{aggregation_group_type_index}"'
    else:
        return default


@dataclass
class ListGroupsResult:
    groups: list[Group]
    has_more: bool


def _escape_clickhouse_like(value: str) -> str:
    """Escape LIKE/ILIKE wildcards so user input matches literally (mirrors Django's ``__icontains``)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_groups(
    team_id: int,
    group_type_index: int,
    *,
    group_key_contains: str = "",
    search: str = "",
    cursor_created_at_us: int = 0,
    cursor_group_key: str = "",
    limit: int = 100,
) -> ListGroupsResult:
    """List groups for the public groups API, served from ClickHouse.

    Filtering, full-text search, ``created_at`` ordering and keyset pagination all run against the
    deduped ``groups`` table, so this never reads the persons Postgres database; results are
    eventually consistent. ``search`` matches a substring of the raw properties JSON or the group
    key exactly (case-insensitive), preserving the previous endpoint's semantics. The keyset cursor
    breaks ``created_at`` ties on ``group_key`` (unique within a team and type).
    """
    from posthog.hogql import ast  # noqa: PLC0415 — keep HogQL off this widely-imported module's import path
    from posthog.hogql.query import execute_hogql_query  # noqa: PLC0415

    from posthog.models.team import Team  # noqa: PLC0415

    team = Team.objects.get(pk=team_id)

    where_exprs: list[ast.Expr] = [
        ast.CompareOperation(
            left=ast.Field(chain=["index"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value=group_type_index),
        )
    ]

    if group_key_contains:
        where_exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.ILike,
                left=ast.Call(name="toString", args=[ast.Field(chain=["key"])]),
                right=ast.Constant(value=f"%{_escape_clickhouse_like(group_key_contains)}%"),
            )
        )

    if search:
        where_exprs.append(
            ast.Or(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.ILike,
                        left=ast.Call(name="toString", args=[ast.Field(chain=["properties"])]),
                        right=ast.Constant(value=f"%{_escape_clickhouse_like(search)}%"),
                    ),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Call(name="lower", args=[ast.Call(name="toString", args=[ast.Field(chain=["key"])])]),
                        right=ast.Call(name="lower", args=[ast.Constant(value=search)]),
                    ),
                ]
            )
        )

    if cursor_created_at_us > 0:
        cursor_dt = datetime.datetime.fromtimestamp(cursor_created_at_us / 1_000_000, tz=datetime.UTC)
        where_exprs.append(
            ast.Or(
                exprs=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Lt,
                        left=ast.Field(chain=["created_at"]),
                        right=ast.Constant(value=cursor_dt),
                    ),
                    ast.And(
                        exprs=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["created_at"]),
                                right=ast.Constant(value=cursor_dt),
                            ),
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Lt,
                                left=ast.Field(chain=["key"]),
                                right=ast.Constant(value=cursor_group_key),
                            ),
                        ]
                    ),
                ]
            )
        )

    query = ast.SelectQuery(
        select=[
            ast.Field(chain=["key"]),
            ast.Field(chain=["created_at"]),
            ast.Field(chain=["properties"]),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
        where=ast.And(exprs=where_exprs),
        order_by=[
            ast.OrderExpr(expr=ast.Field(chain=["created_at"]), order="DESC"),
            ast.OrderExpr(expr=ast.Field(chain=["key"]), order="DESC"),
        ],
        limit=ast.Constant(value=limit + 1),
    )

    response = execute_hogql_query(query, team=team, query_type="groups_list")

    rows = response.results or []
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    groups = [
        Group(
            team_id=team_id,
            group_type_index=group_type_index,
            group_key=group_key,
            group_properties=(
                json.loads(group_properties)
                if isinstance(group_properties, str) and group_properties
                else (group_properties or {})
            ),
            created_at=created_at,
        )
        for group_key, created_at, group_properties in rows
    ]
    return ListGroupsResult(groups=groups, has_more=has_more)

import json
import datetime
from dataclasses import dataclass
from typing import Optional, Union
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils.timezone import now

import structlog
from dateutil.parser import isoparse

from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_GROUPS
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.group.group import Group
from posthog.models.group.sql import INSERT_GROUP_SQL

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

    from posthog.personhog_client.client import personhog_call, require_personhog_client
    from posthog.personhog_client.converters import proto_group_to_model
    from posthog.personhog_client.proto import CreateGroupRequest

    client = require_personhog_client()
    return personhog_call(
        "create_group",
        lambda: proto_group_to_model(
            client.create_group(
                CreateGroupRequest(
                    team_id=team_id,
                    group_type_index=group_type_index,
                    group_key=group_key,
                    group_properties=json.dumps(properties).encode(),
                    created_at=int(timestamp.timestamp() * 1000),
                )
            ).group
        ),
        caller_tag="group/create_group",
    )


def save_group(group: Group, *, operation: str = "group_save") -> None:
    """Save a Group's group_properties via personhog. Only group_properties is synced."""
    from posthog.personhog_client.client import personhog_call, require_personhog_client
    from posthog.personhog_client.proto import UpdateGroupRequest

    client = require_personhog_client()

    def _update() -> None:
        client.update_group(
            UpdateGroupRequest(
                team_id=group.team_id,
                group_type_index=group.group_type_index,
                group_key=group.group_key,
                update_mask=["group_properties"],
                group_properties=json.dumps(group.group_properties).encode(),
            )
        )

    personhog_call(operation, _update, caller_tag="group/save_group")


def get_group_by_key(team_id: int, group_type_index: int, group_key: str) -> Group | None:
    """Fetch a single Group via personhog. Returns None when the group does not exist."""
    from posthog.personhog_client.client import personhog_call, require_personhog_client
    from posthog.personhog_client.converters import proto_group_to_model
    from posthog.personhog_client.proto import GetGroupRequest

    client = require_personhog_client()

    def _fetch() -> Group | None:
        resp = client.get_group(
            GetGroupRequest(team_id=team_id, group_type_index=group_type_index, group_key=group_key)
        )
        if resp.group and resp.group.id:
            return proto_group_to_model(resp.group)
        return None

    return personhog_call("get_group_by_key", _fetch, caller_tag="group/get_group_by_key")


def get_groups_by_identifiers(team_id: int, group_type_index: int, group_keys: list[str]) -> list[Group]:
    """Fetch multiple Groups via personhog."""
    from posthog.personhog_client.client import personhog_call, require_personhog_client
    from posthog.personhog_client.converters import proto_group_to_model
    from posthog.personhog_client.proto import GetGroupsRequest, GroupIdentifier

    if not group_keys:
        return []

    client = require_personhog_client()

    def _fetch() -> list[Group]:
        groups: list[Group] = []
        for i in range(0, len(group_keys), settings.PERSONHOG_BATCH_SIZE):
            identifiers = [
                GroupIdentifier(group_type_index=group_type_index, group_key=key)
                for key in group_keys[i : i + settings.PERSONHOG_BATCH_SIZE]
            ]
            resp = client.get_groups(GetGroupsRequest(team_id=team_id, group_identifiers=identifiers))
            groups.extend(proto_group_to_model(g) for g in resp.groups if g.id)
        return groups

    return personhog_call("get_groups_by_identifiers", _fetch, caller_tag="group/get_groups_by_identifiers")


def get_groups_by_type_indices(team_id: int, group_type_indices: set[int], group_keys: set[str]) -> list[Group]:
    """Fetch Groups across multiple group type indices in a single call.

    Creates a GroupIdentifier for each (group_type_index, group_key) combination
    and fetches them all in one gRPC/ORM call."""
    from posthog.personhog_client.client import personhog_call, require_personhog_client
    from posthog.personhog_client.converters import proto_group_to_model
    from posthog.personhog_client.proto import GetGroupsRequest, GroupIdentifier

    if not group_type_indices or not group_keys:
        return []

    client = require_personhog_client()

    def _fetch() -> list[Group]:
        identifiers = [
            GroupIdentifier(group_type_index=gti, group_key=key) for gti in group_type_indices for key in group_keys
        ]
        groups: list[Group] = []
        for i in range(0, len(identifiers), settings.PERSONHOG_BATCH_SIZE):
            resp = client.get_groups(
                GetGroupsRequest(team_id=team_id, group_identifiers=identifiers[i : i + settings.PERSONHOG_BATCH_SIZE])
            )
            groups.extend(proto_group_to_model(g) for g in resp.groups if g.id)
        return groups

    return personhog_call("get_groups_by_type_indices", _fetch, caller_tag="group/get_groups_by_type_indices")


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

import json
import datetime
from typing import Optional, Union
from zoneinfo import ZoneInfo

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
    group = Group.objects.create(  # nosemgrep: no-direct-persons-db-orm
        team_id=team_id,
        group_type_index=group_type_index,
        group_key=group_key,
        group_properties=properties,
        created_at=timestamp,
        version=0,
    )
    return group


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
            identifiers = [GroupIdentifier(group_type_index=group_type_index, group_key=key) for key in group_keys]
            resp = client.get_groups(GetGroupsRequest(team_id=team_id, group_identifiers=identifiers))
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="get_groups_by_identifiers", source="personhog", client_name=get_client_name()
            ).inc()
            return [proto_group_to_model(g) for g in resp.groups if g.id]
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
            resp = client.get_groups(GetGroupsRequest(team_id=team_id, group_identifiers=identifiers))
            PERSONHOG_ROUTING_TOTAL.labels(
                operation="get_groups_by_type_indices", source="personhog", client_name=get_client_name()
            ).inc()
            return [proto_group_to_model(g) for g in resp.groups if g.id]
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

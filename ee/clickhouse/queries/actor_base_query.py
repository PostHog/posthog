import json
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from rest_framework import serializers

from ee.clickhouse.client import sync_execute
from posthog.models import Entity, Filter, Team


class ActorResponse(TypedDict):
    id: str
    created_at: Optional[str]
    properties: Dict[str, Any]
    is_identified: Optional[bool]
    name: str
    distinct_ids: List[str]


class ActorBaseQuery:
    aggregating_by_groups = False

    def __init__(self, team: Team, filter: Filter, entity: Optional[Entity] = None):
        self.team = team
        self.entity = entity
        self.filter = filter

        if self.entity and self.entity.math == "unique_group":
            self.aggregating_by_groups = True

    def groups_query(self) -> Tuple[str, Dict]:
        raise NotImplementedError()

    def people_query(self) -> Tuple[str, Dict]:
        raise NotImplementedError()

    def get_actor_query(self) -> Tuple[str, Dict]:
        if self.aggregating_by_groups:
            query, params = self.groups_query()
            return query, params
        else:
            query, params = self.people_query()
            return query, params

    def get_actors(self) -> List[ActorResponse]:
        query, params = self.get_actor_query()
        raw_result: List[Dict[str, Any]] = sync_execute(query, params, as_dict=True)
        res: List[ActorResponse] = []
        for row in raw_result:
            actor = self._serialize(row)
            if actor:
                res.append(actor)
        return res

    def _serialize(self, data: Dict[str, Any]) -> Optional[ActorResponse]:
        id = data.get("id", None)
        if not id:
            return None
        created_at = data.get("created_at", None)
        properties = json.loads(data.get("properties", "{}"))
        is_identified: Optional[bool] = data.get("is_identified", None)
        alias: str = properties.get("email", None) or properties.get("name", None)
        distinct_ids: List[str] = data.get("distinct_ids", [])
        return ActorResponse(
            id=id,
            created_at=created_at,
            properties=properties,
            is_identified=is_identified,
            name=alias or id,
            distinct_ids=distinct_ids,
        )


def format_select_fields(fields: Dict[str, str]) -> str:
    return " ".join(f", {selector} AS {column_name}" for column_name, selector in fields.items())

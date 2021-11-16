import json
from typing import Any, Dict, List, Optional, Tuple, TypedDict

from rest_framework import serializers

from ee.clickhouse.client import sync_execute
from posthog.models import Entity, Filter, Team


class ActorResponse(TypedDict):
    id: str
    created_at: str
    properties: List[Dict[str, Any]]
    is_identified: Optional[bool]
    name: str
    distinct_ids: Optional[List[str]]


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

    def get_query(self) -> Tuple[str, Dict]:
        if self.aggregating_by_groups:
            query, params = self.groups_query()
            return query, params
        else:
            query, params = self.people_query()
            return query, params

    def get_actors(self) -> List[ActorResponse]:
        query, params = self.get_query()
        raw_result = sync_execute(query, params, as_dict=True)
        return ActorSerializer(raw_result, many=True).data


class ActorSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()
    properties = serializers.SerializerMethodField()
    is_identified = serializers.SerializerMethodField()
    name = serializers.SerializerMethodField()
    distinct_ids = serializers.SerializerMethodField()

    def get_id(self, obj):
        return obj["id"]

    def get_created_at(self, obj):
        return obj["created_at"]

    def get_properties(self, obj):
        return json.loads(obj["properties"])

    def get_is_identified(self, obj):
        return obj.get("is_identified", None)

    def get_name(self, obj):
        props = self.get_properties(obj)
        alias = props.get("email", None) or props.get("name", None)
        return alias or obj["id"]

    def get_distinct_ids(self, obj):
        return obj.get("distinct_ids", None)

from django.db import transaction
from django.db.models import F, Value
from django.db.models.expressions import CombinedExpression
from rest_framework import serializers, viewsets

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.hogql import ast
from posthog.warehouse.models import DataWarehouseModel, DataWarehouseModelPath

POSTHOG_ROOT_SOURCES = {
    "events",
    "groups",
    "persons",
    "person_distinct_ids",
    "session_replay_events",
    "cohort_people",
    "static_cohort_people",
    "log_entries",
    "sessions",
    "heatmaps",
}


class DataWarehouseModelSerializer(serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)

    class Meta:
        model = DataWarehouseModel
        fields = [
            "id",
            "deleted",
            "name",
            "query",
            "created_by",
            "created_at",
            "materialization",
            "incremental_key",
            "unique_key",
        ]
        read_only_fields = ["id", "created_by", "created_at", "deleted"]

    def create(self, validated_data):
        validated_data["team_id"] = self.context["team_id"]
        validated_data["created_by"] = self.context["request"].user

        model = DataWarehouseModel(**validated_data)

        hogql_query = model.hogql_query()
        if isinstance(hogql_query, ast.SelectUnionQuery):
            queries = hogql_query.select_queries
        else:
            queries = [hogql_query]

        parents = set()
        while queries:
            query = queries.pop()

            if isinstance(query.select_from.table, ast.SelectQuery):
                queries.append(query.select_from.table)
            elif isinstance(query.select_from.table, ast.SelectUnionQuery):
                queries.extend(query.select_from.table.select_queries)

            join = query.select_from
            while join is not None:
                parents.add(join.table.chain[0])
                join = join.next_join

        with transaction.atomic():
            model.save()

            # Match parents that are leafs.
            leaf_query = "*." + "|".join(parent for parent in parents)
            # We only need to append ourselves as a new leaf.
            DataWarehouseModelPath.objects.filter(path__lquery=leaf_query).update(
                path=CombinedExpression(F("path"), "||", Value(model.id.hex))
            )

            # Match parents that are not leafs.
            query = "*{1,}." + "|".join(parent for parent in parents) + ".*{1,}"
            # We need to create a new branch.
            for model_path in DataWarehouseModelPath.objects.filter(path__lquery=leaf_query):
                new_path = DataWarehouseModelPath(path=[model_path.path, model.id.hex], team=model.team)
                new_path.save()

            for parent in parents:
                if parent not in POSTHOG_ROOT_SOURCES:
                    continue

                new_path = DataWarehouseModelPath(path=[parent, model.id.hex], team=model.team, deleted=False)

                new_path.save()

        return model


class DataWarehouseModelViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "warehouse_models"
    queryset = DataWarehouseModel.objects.all()
    serializer_class = DataWarehouseModelSerializer

from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models.resource_transfer.types import ResourcePayload, ResourceTransferEdge
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor
from posthog.models.resource_transfer.visitors.common import (
    build_edges_for_ids,
    collect_cohort_ids_from_properties,
    rewrite_cohort_breakdown,
    rewrite_cohort_id_in_properties,
)


class InsightVisitor(
    ResourceTransferVisitor,
    kind="Insight",
    excluded_fields=[
        "dive_dashboard",
        "dashboard",
        "dashboards",
        "short_id",
        "filters_hash",
        "refreshing",
        "refresh_attempt",
        "last_refresh",
        "last_modified_at",
    ],
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Insight

        return Insight

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        from posthog.models import Action, Cohort

        action_ids = cls._extract_action_ids(resource.filters, resource.query)
        cohort_ids = cls._extract_cohort_ids(resource.filters, resource.query)

        edges: list[ResourceTransferEdge] = []
        edges.extend(build_edges_for_ids(action_ids, Action, "action", cls._rewrite_action_in_payload))
        edges.extend(build_edges_for_ids(cohort_ids, Cohort, "cohort", cls._rewrite_cohort_in_payload))
        return edges

    @classmethod
    def _rewrite_action_in_payload(cls, payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
        result = {**payload}
        if result.get("filters"):
            result["filters"] = cls._rewrite_action_id_in_filters(result["filters"], old_pk, new_pk)
        if result.get("query"):
            result["query"] = cls._rewrite_action_id_in_query(result["query"], old_pk, new_pk)
        return result

    @classmethod
    def _rewrite_cohort_in_payload(cls, payload: ResourcePayload, old_pk: Any, new_pk: Any) -> ResourcePayload:
        result = {**payload}
        if result.get("filters"):
            result["filters"] = cls._rewrite_cohort_id_in_filters(result["filters"], old_pk, new_pk)
        if result.get("query"):
            result["query"] = cls._rewrite_cohort_id_in_query(result["query"], old_pk, new_pk)
        return result

    @classmethod
    def _extract_action_ids(cls, filters: dict | None, query: dict | None) -> set[int]:
        ids: set[int] = set()
        if filters:
            ids.update(cls._extract_action_ids_from_filters(filters))
        if query:
            ids.update(cls._extract_action_ids_from_query(query))
        return ids

    @classmethod
    def _extract_cohort_ids(cls, filters: dict | None, query: dict | None) -> set[int]:
        ids: set[int] = set()
        if filters:
            ids.update(cls._extract_cohort_ids_from_filters(filters))
        if query:
            ids.update(cls._extract_cohort_ids_from_query(query))
        return ids

    @classmethod
    def _extract_action_ids_from_filters(cls, filters: dict) -> set[int]:
        ids: set[int] = set()

        # filters.actions[].id
        for action in filters.get("actions", []):
            if isinstance(action, dict) and action.get("id") is not None:
                ids.add(int(action["id"]))

        # filters.exclusions[].id where type == "actions"
        for exclusion in filters.get("exclusions", []):
            if isinstance(exclusion, dict) and exclusion.get("type") == "actions" and exclusion.get("id") is not None:
                ids.add(int(exclusion["id"]))

        # filters.target_entity and filters.returning_entity (retention)
        for key in ("target_entity", "returning_entity"):
            entity = filters.get(key)
            if isinstance(entity, dict) and entity.get("type") == "actions" and entity.get("id") is not None:
                ids.add(int(entity["id"]))

        return ids

    @classmethod
    def _extract_action_ids_from_query(cls, query: dict) -> set[int]:
        ids: set[int] = set()
        source = query.get("source", {})
        if not isinstance(source, dict):
            return ids

        # source.series[] where kind == "ActionsNode"
        for series_item in source.get("series", []):
            if (
                isinstance(series_item, dict)
                and series_item.get("kind") == "ActionsNode"
                and series_item.get("id") is not None
            ):
                ids.add(int(series_item["id"]))

        # source.funnelsFilter.exclusions[] where kind == "ActionsNode"
        funnels_filter = source.get("funnelsFilter", {})
        if isinstance(funnels_filter, dict):
            for exclusion in funnels_filter.get("exclusions", []):
                if (
                    isinstance(exclusion, dict)
                    and exclusion.get("kind") == "ActionsNode"
                    and exclusion.get("id") is not None
                ):
                    ids.add(int(exclusion["id"]))

        # source.retentionFilter.targetEntity / returningEntity where type == "actions"
        retention_filter = source.get("retentionFilter", {})
        if isinstance(retention_filter, dict):
            for key in ("targetEntity", "returningEntity"):
                entity = retention_filter.get(key)
                if isinstance(entity, dict) and entity.get("type") == "actions" and entity.get("id") is not None:
                    ids.add(int(entity["id"]))

        # source.conversionGoal.actionId
        conversion_goal = source.get("conversionGoal", {})
        if isinstance(conversion_goal, dict) and conversion_goal.get("actionId") is not None:
            ids.add(int(conversion_goal["actionId"]))

        # source.actionId (SessionsQuery and web analytics queries)
        if source.get("actionId") is not None:
            ids.add(int(source["actionId"]))

        return ids

    @classmethod
    def _extract_cohort_ids_from_filters(cls, filters: dict) -> set[int]:
        ids: set[int] = set()

        # top-level properties
        ids.update(collect_cohort_ids_from_properties(filters.get("properties")))

        # entity-level properties (actions[].properties and events[].properties)
        for entity_list_key in ("actions", "events", "exclusions"):
            for entity in filters.get(entity_list_key, []):
                if isinstance(entity, dict):
                    ids.update(collect_cohort_ids_from_properties(entity.get("properties")))

        # retention entity properties
        for key in ("target_entity", "returning_entity"):
            entity = filters.get(key)
            if isinstance(entity, dict):
                ids.update(collect_cohort_ids_from_properties(entity.get("properties")))

        # breakdown cohorts: breakdown_type == "cohort" means breakdown is cohort ID(s)
        if filters.get("breakdown_type") == "cohort":
            breakdown = filters.get("breakdown")
            if isinstance(breakdown, list):
                for item in breakdown:
                    if isinstance(item, int):
                        ids.add(item)
            elif isinstance(breakdown, int):
                ids.add(breakdown)

        return ids

    @classmethod
    def _extract_cohort_ids_from_query(cls, query: dict) -> set[int]:
        ids: set[int] = set()
        source = query.get("source", {})
        if not isinstance(source, dict):
            return ids

        # top-level properties
        ids.update(collect_cohort_ids_from_properties(source.get("properties")))

        # series[].properties and series[].fixedProperties
        for series_item in source.get("series", []):
            if isinstance(series_item, dict):
                ids.update(collect_cohort_ids_from_properties(series_item.get("properties")))
                ids.update(collect_cohort_ids_from_properties(series_item.get("fixedProperties")))

        # retention entity properties
        retention_filter = source.get("retentionFilter", {})
        if isinstance(retention_filter, dict):
            for key in ("targetEntity", "returningEntity"):
                entity = retention_filter.get(key)
                if isinstance(entity, dict):
                    ids.update(collect_cohort_ids_from_properties(entity.get("properties")))

        # breakdown cohorts
        breakdown_filter = source.get("breakdownFilter", {})
        if isinstance(breakdown_filter, dict) and breakdown_filter.get("breakdown_type") == "cohort":
            breakdown = breakdown_filter.get("breakdown")
            if isinstance(breakdown, list):
                for item in breakdown:
                    if isinstance(item, int):
                        ids.add(item)
            elif isinstance(breakdown, int):
                ids.add(breakdown)

        return ids

    # --- rewriting JSON-embedded references ---

    @classmethod
    def _replace_id_in_entity_list(
        cls, entities: list, old_pk: int, new_pk: int, type_filter: str | None = None
    ) -> list:
        result = []
        for entity in entities:
            if not isinstance(entity, dict):
                result.append(entity)
                continue
            if type_filter is not None and entity.get("type") != type_filter:
                result.append(entity)
                continue
            if entity.get("id") is not None and int(entity["id"]) == old_pk:
                entity = {**entity, "id": new_pk}
            result.append(entity)
        return result

    @classmethod
    def _rewrite_action_id_in_filters(cls, filters: dict, old_pk: int, new_pk: int) -> dict:
        result = {**filters}

        if "actions" in result:
            result["actions"] = cls._replace_id_in_entity_list(result["actions"], old_pk, new_pk)

        if "exclusions" in result:
            result["exclusions"] = cls._replace_id_in_entity_list(
                result["exclusions"], old_pk, new_pk, type_filter="actions"
            )

        for key in ("target_entity", "returning_entity"):
            entity = result.get(key)
            if (
                isinstance(entity, dict)
                and entity.get("type") == "actions"
                and entity.get("id") is not None
                and int(entity["id"]) == old_pk
            ):
                result[key] = {**entity, "id": new_pk}

        return result

    @classmethod
    def _rewrite_action_id_in_query(cls, query: dict, old_pk: int, new_pk: int) -> dict:
        result = {**query}
        source = result.get("source")
        if not isinstance(source, dict):
            return result

        source = {**source}
        result["source"] = source

        # series
        if "series" in source:
            new_series = []
            for item in source["series"]:
                if (
                    isinstance(item, dict)
                    and item.get("kind") == "ActionsNode"
                    and item.get("id") is not None
                    and int(item["id"]) == old_pk
                ):
                    new_series.append({**item, "id": new_pk})
                else:
                    new_series.append(item)
            source["series"] = new_series

        # funnelsFilter.exclusions
        if "funnelsFilter" in source and isinstance(source["funnelsFilter"], dict):
            ff = {**source["funnelsFilter"]}
            if "exclusions" in ff:
                new_exc = []
                for item in ff["exclusions"]:
                    if (
                        isinstance(item, dict)
                        and item.get("kind") == "ActionsNode"
                        and item.get("id") is not None
                        and int(item["id"]) == old_pk
                    ):
                        new_exc.append({**item, "id": new_pk})
                    else:
                        new_exc.append(item)
                ff["exclusions"] = new_exc
            source["funnelsFilter"] = ff

        # retentionFilter.targetEntity / returningEntity
        if "retentionFilter" in source and isinstance(source["retentionFilter"], dict):
            rf = {**source["retentionFilter"]}
            for key in ("targetEntity", "returningEntity"):
                entity = rf.get(key)
                if (
                    isinstance(entity, dict)
                    and entity.get("type") == "actions"
                    and entity.get("id") is not None
                    and int(entity["id"]) == old_pk
                ):
                    rf[key] = {**entity, "id": new_pk}
            source["retentionFilter"] = rf

        # conversionGoal.actionId
        if "conversionGoal" in source and isinstance(source["conversionGoal"], dict):
            cg = source["conversionGoal"]
            if cg.get("actionId") is not None and int(cg["actionId"]) == old_pk:
                source["conversionGoal"] = {**cg, "actionId": new_pk}

        # source.actionId
        if source.get("actionId") is not None and int(source["actionId"]) == old_pk:
            source["actionId"] = new_pk

        return result

    @classmethod
    def _rewrite_cohort_id_in_filters(cls, filters: dict, old_pk: int, new_pk: int) -> dict:
        result = {**filters}

        if "properties" in result:
            result["properties"] = rewrite_cohort_id_in_properties(result["properties"], old_pk, new_pk)

        for entity_list_key in ("actions", "events", "exclusions"):
            if entity_list_key in result and isinstance(result[entity_list_key], list):
                new_entities = []
                for entity in result[entity_list_key]:
                    if isinstance(entity, dict) and "properties" in entity:
                        entity = {
                            **entity,
                            "properties": rewrite_cohort_id_in_properties(entity["properties"], old_pk, new_pk),
                        }
                    new_entities.append(entity)
                result[entity_list_key] = new_entities

        for key in ("target_entity", "returning_entity"):
            entity = result.get(key)
            if isinstance(entity, dict) and "properties" in entity:
                result[key] = {
                    **entity,
                    "properties": rewrite_cohort_id_in_properties(entity["properties"], old_pk, new_pk),
                }

        if result.get("breakdown_type") == "cohort" and "breakdown" in result:
            result["breakdown"] = rewrite_cohort_breakdown(result["breakdown"], old_pk, new_pk)

        return result

    @classmethod
    def _rewrite_cohort_id_in_query(cls, query: dict, old_pk: int, new_pk: int) -> dict:
        result = {**query}
        source = result.get("source")
        if not isinstance(source, dict):
            return result

        source = {**source}
        result["source"] = source

        if "properties" in source:
            source["properties"] = rewrite_cohort_id_in_properties(source["properties"], old_pk, new_pk)

        if "series" in source:
            new_series = []
            for item in source["series"]:
                if isinstance(item, dict):
                    item = {**item}
                    if "properties" in item:
                        item["properties"] = rewrite_cohort_id_in_properties(item["properties"], old_pk, new_pk)
                    if "fixedProperties" in item:
                        item["fixedProperties"] = rewrite_cohort_id_in_properties(
                            item["fixedProperties"], old_pk, new_pk
                        )
                new_series.append(item)
            source["series"] = new_series

        if "retentionFilter" in source and isinstance(source["retentionFilter"], dict):
            rf = {**source["retentionFilter"]}
            for key in ("targetEntity", "returningEntity"):
                entity = rf.get(key)
                if isinstance(entity, dict) and "properties" in entity:
                    rf[key] = {
                        **entity,
                        "properties": rewrite_cohort_id_in_properties(entity["properties"], old_pk, new_pk),
                    }
            source["retentionFilter"] = rf

        if "breakdownFilter" in source and isinstance(source["breakdownFilter"], dict):
            bf = {**source["breakdownFilter"]}
            if bf.get("breakdown_type") == "cohort" and "breakdown" in bf:
                bf["breakdown"] = rewrite_cohort_breakdown(bf["breakdown"], old_pk, new_pk)
            source["breakdownFilter"] = bf

        return result

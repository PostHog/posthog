from __future__ import annotations

from typing import Any

from django.db import models

from posthog.models.resource_transfer.types import ResourceMap, ResourcePayload, ResourceTransferEdge, RewriteRelationFn
from posthog.models.resource_transfer.visitors.base import ResourceTransferVisitor


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

        edges: list[ResourceTransferEdge] = []
        action_ids = cls._extract_action_ids(resource.filters, resource.query)
        cohort_ids = cls._extract_cohort_ids(resource.filters, resource.query)

        for action_id in action_ids:
            edges.append(
                ResourceTransferEdge(
                    name=f"action:{action_id}",
                    target_model=Action,
                    target_primary_key=action_id,
                    rewrite_relation=cls._make_json_id_rewriter(Action, action_id),
                )
            )

        for cohort_id in cohort_ids:
            edges.append(
                ResourceTransferEdge(
                    name=f"cohort:{cohort_id}",
                    target_model=Cohort,
                    target_primary_key=cohort_id,
                    rewrite_relation=cls._make_json_id_rewriter(Cohort, cohort_id),
                )
            )

        return edges

    # --- extracting JSON-embedded references ---

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
    def _collect_cohort_ids_from_properties(cls, properties: Any) -> set[int]:
        ids: set[int] = set()
        if isinstance(properties, list):
            for prop in properties:
                if isinstance(prop, dict) and prop.get("type") == "cohort" and prop.get("value") is not None:
                    ids.add(int(prop["value"]))
        elif isinstance(properties, dict):
            if properties.get("type") == "cohort" and properties.get("value") is not None:
                ids.add(int(properties["value"]))
            # grouped property format: {"type": "AND"/"OR", "values": [...]}
            for group in properties.get("values", []):
                if isinstance(group, dict):
                    ids.update(cls._collect_cohort_ids_from_properties(group.get("values", [])))
        return ids

    @classmethod
    def _extract_cohort_ids_from_filters(cls, filters: dict) -> set[int]:
        ids: set[int] = set()

        # top-level properties
        ids.update(cls._collect_cohort_ids_from_properties(filters.get("properties")))

        # entity-level properties (actions[].properties and events[].properties)
        for entity_list_key in ("actions", "events", "exclusions"):
            for entity in filters.get(entity_list_key, []):
                if isinstance(entity, dict):
                    ids.update(cls._collect_cohort_ids_from_properties(entity.get("properties")))

        # retention entity properties
        for key in ("target_entity", "returning_entity"):
            entity = filters.get(key)
            if isinstance(entity, dict):
                ids.update(cls._collect_cohort_ids_from_properties(entity.get("properties")))

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
        ids.update(cls._collect_cohort_ids_from_properties(source.get("properties")))

        # series[].properties and series[].fixedProperties
        for series_item in source.get("series", []):
            if isinstance(series_item, dict):
                ids.update(cls._collect_cohort_ids_from_properties(series_item.get("properties")))
                ids.update(cls._collect_cohort_ids_from_properties(series_item.get("fixedProperties")))

        # retention entity properties
        retention_filter = source.get("retentionFilter", {})
        if isinstance(retention_filter, dict):
            for key in ("targetEntity", "returningEntity"):
                entity = retention_filter.get(key)
                if isinstance(entity, dict):
                    ids.update(cls._collect_cohort_ids_from_properties(entity.get("properties")))

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
    def _make_json_id_rewriter(cls, target_model: type[models.Model], old_pk: Any) -> RewriteRelationFn:
        def _rewrite(
            payload: ResourcePayload,
            resource_map: ResourceMap,
        ) -> ResourcePayload:
            target_visitor = ResourceTransferVisitor.get_visitor(target_model)

            if target_visitor is None:
                raise TypeError(f"Could not rewrite {target_model.__name__} because it has no configured visitor")

            vertex = resource_map.get((target_visitor.kind, old_pk))
            if vertex is None:
                raise ValueError(
                    f"Could not rewrite JSON reference to {target_model.__name__}(pk={old_pk}): "
                    "resource not found in map"
                )

            if vertex.duplicated_resource is None:
                raise ValueError(
                    f"Could not rewrite JSON reference to {target_model.__name__}(pk={old_pk}): resource not duplicated yet"
                )

            new_pk = vertex.duplicated_resource.pk

            from posthog.models import Action, Cohort

            result = {**payload}
            if target_model is Action:
                if result.get("filters"):
                    result["filters"] = cls._rewrite_action_id_in_filters(result["filters"], old_pk, new_pk)
                if result.get("query"):
                    result["query"] = cls._rewrite_action_id_in_query(result["query"], old_pk, new_pk)
            elif target_model is Cohort:
                if result.get("filters"):
                    result["filters"] = cls._rewrite_cohort_id_in_filters(result["filters"], old_pk, new_pk)
                if result.get("query"):
                    result["query"] = cls._rewrite_cohort_id_in_query(result["query"], old_pk, new_pk)

            return result

        return _rewrite

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
    def _rewrite_cohort_id_in_properties(cls, properties: Any, old_pk: int, new_pk: int) -> Any:
        if isinstance(properties, list):
            result = []
            for prop in properties:
                if (
                    isinstance(prop, dict)
                    and prop.get("type") == "cohort"
                    and prop.get("value") is not None
                    and int(prop["value"]) == old_pk
                ):
                    result.append({**prop, "value": new_pk})
                else:
                    result.append(prop)
            return result
        elif isinstance(properties, dict):
            result_dict = {**properties}
            if (
                result_dict.get("type") == "cohort"
                and result_dict.get("value") is not None
                and int(result_dict["value"]) == old_pk
            ):
                result_dict["value"] = new_pk
            if "values" in result_dict:
                new_values = []
                for group in result_dict["values"]:
                    if isinstance(group, dict):
                        new_group = {**group}
                        if "values" in new_group:
                            new_group["values"] = cls._rewrite_cohort_id_in_properties(
                                new_group["values"], old_pk, new_pk
                            )
                        new_values.append(new_group)
                    else:
                        new_values.append(group)
                result_dict["values"] = new_values
            return result_dict
        return properties

    @classmethod
    def _rewrite_cohort_breakdown(cls, breakdown: Any, old_pk: int, new_pk: int) -> Any:
        if isinstance(breakdown, list):
            return [new_pk if isinstance(item, int) and item == old_pk else item for item in breakdown]
        elif isinstance(breakdown, int) and breakdown == old_pk:
            return new_pk
        return breakdown

    @classmethod
    def _rewrite_cohort_id_in_filters(cls, filters: dict, old_pk: int, new_pk: int) -> dict:
        result = {**filters}

        if "properties" in result:
            result["properties"] = cls._rewrite_cohort_id_in_properties(result["properties"], old_pk, new_pk)

        for entity_list_key in ("actions", "events", "exclusions"):
            if entity_list_key in result and isinstance(result[entity_list_key], list):
                new_entities = []
                for entity in result[entity_list_key]:
                    if isinstance(entity, dict) and "properties" in entity:
                        entity = {
                            **entity,
                            "properties": cls._rewrite_cohort_id_in_properties(entity["properties"], old_pk, new_pk),
                        }
                    new_entities.append(entity)
                result[entity_list_key] = new_entities

        for key in ("target_entity", "returning_entity"):
            entity = result.get(key)
            if isinstance(entity, dict) and "properties" in entity:
                result[key] = {
                    **entity,
                    "properties": cls._rewrite_cohort_id_in_properties(entity["properties"], old_pk, new_pk),
                }

        if result.get("breakdown_type") == "cohort" and "breakdown" in result:
            result["breakdown"] = cls._rewrite_cohort_breakdown(result["breakdown"], old_pk, new_pk)

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
            source["properties"] = cls._rewrite_cohort_id_in_properties(source["properties"], old_pk, new_pk)

        if "series" in source:
            new_series = []
            for item in source["series"]:
                if isinstance(item, dict):
                    item = {**item}
                    if "properties" in item:
                        item["properties"] = cls._rewrite_cohort_id_in_properties(item["properties"], old_pk, new_pk)
                    if "fixedProperties" in item:
                        item["fixedProperties"] = cls._rewrite_cohort_id_in_properties(
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
                        "properties": cls._rewrite_cohort_id_in_properties(entity["properties"], old_pk, new_pk),
                    }
            source["retentionFilter"] = rf

        if "breakdownFilter" in source and isinstance(source["breakdownFilter"], dict):
            bf = {**source["breakdownFilter"]}
            if bf.get("breakdown_type") == "cohort" and "breakdown" in bf:
                bf["breakdown"] = cls._rewrite_cohort_breakdown(bf["breakdown"], old_pk, new_pk)
            source["breakdownFilter"] = bf

        return result

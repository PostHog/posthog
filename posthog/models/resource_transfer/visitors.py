from abc import abstractmethod
from typing import Any

from django.db import models
from django.db.models import query_utils
from django.db.models.fields import related_descriptors

from posthog.models.resource_transfer.types import (
    ResourceKind,
    ResourceMap,
    ResourcePayload,
    ResourceTransferEdge,
    RewriteRelationFn,
)
from posthog.models.utils import UUIDTClassicModel


class ResourceTransferVisitor:
    __VISITORS: list[type["ResourceTransferVisitor"]] = []

    kind: ResourceKind
    excluded_fields: list[str]
    immutable: bool
    friendly_name: str
    user_facing: bool

    def __init_subclass__(
        cls,
        kind: ResourceKind,
        excluded_fields: list[str] | None = None,
        immutable: bool = False,
        friendly_name: str | None = None,
        user_facing: bool = True,
    ) -> None:
        cls.kind = kind
        cls.excluded_fields = excluded_fields or []
        cls.immutable = immutable
        cls.friendly_name = friendly_name if friendly_name is not None else kind
        cls.user_facing = user_facing

        ResourceTransferVisitor.__VISITORS.append(cls)

    @classmethod
    @abstractmethod
    def get_model(cls) -> type[models.Model]:
        """
        Subclasses should override this function to define the model which backs the resource kind.
        """

    @classmethod
    def get_dynamic_edges(cls, resource: Any) -> list[ResourceTransferEdge]:
        """
        Override to return extra edges at runtime. This is useful for schemas where foreign keys might be stored in untyped columns like JSON.
        """
        return []

    @classmethod
    def get_display_name(cls, resource: Any) -> str:
        """
        Return a human-readable name for a resource instance. Override in subclasses for custom behavior.
        Falls back to the resource's `name` attribute if present, otherwise uses kind + pk.
        """
        if hasattr(resource, "name") and resource.name:
            return str(resource.name)
        return f"{cls.kind} {resource.pk}"

    @staticmethod
    def get_visitor(kind_or_value: ResourceKind | Any) -> type["ResourceTransferVisitor"] | None:
        if isinstance(kind_or_value, str):
            return next(
                (visitor for visitor in ResourceTransferVisitor.__VISITORS if visitor.kind == kind_or_value), None
            )

        if isinstance(kind_or_value, type):
            return next(
                (visitor for visitor in ResourceTransferVisitor.__VISITORS if visitor.get_model() is kind_or_value),
                None,
            )

        return next(
            (visitor for visitor in ResourceTransferVisitor.__VISITORS if visitor.get_model() is type(kind_or_value)),
            None,
        )

    @classmethod
    def should_touch_field(cls, field_name: str) -> bool:
        # ignore private fields
        if field_name.startswith("_"):
            return False

        # ignore excluded fields
        if field_name in cls.excluded_fields:
            return False

        if cls.is_primary_key(field_name):
            return False

        if issubclass(cls.get_model(), UUIDTClassicModel) and field_name == "uuid":
            # UUIDTClassicModel adds a unique uuid column that is not a primary key and can break stuff
            return False

        # ignore fields that aren't a django model field
        class_attr = getattr(cls.get_model(), field_name)

        if (
            isinstance(class_attr, query_utils.DeferredAttribute)
            and not isinstance(
                class_attr,
                related_descriptors.ForeignKeyDeferredAttribute,  # ForeignKeyDeferredAttribute is used for fields that are automatically added to models as a part of a ForeignKeyField. we skip this to ensure we don't accidentally copy old relations
            )
        ):
            # it is a simple primitive column (not a relation)
            return True

        # it is a relation which is a more complicated scenario
        return isinstance(
            class_attr,
            (
                related_descriptors.ForwardManyToOneDescriptor,  # ex: Dashboard.team
                # related_descriptors.ReverseManyToOneDescriptor,  # ex: Dashboard.tiles
                related_descriptors.ForwardOneToOneDescriptor,
                related_descriptors.ManyToManyDescriptor,  # ex: Dashboard.insights
            ),
        )

    @classmethod
    def is_relation(cls, field_name: str) -> bool:
        backing_model = cls.get_model()
        field_definition = getattr(backing_model, field_name)

        if field_definition is None:
            return False

        # I think these are the only related object fields: https://docs.djangoproject.com/en/6.0/ref/models/relations/
        return isinstance(
            field_definition,
            (
                related_descriptors.ManyToManyDescriptor,
                related_descriptors.ReverseManyToOneDescriptor,
                related_descriptors.ForwardManyToOneDescriptor,
                related_descriptors.ForwardOneToOneDescriptor,
            ),
        )

    @classmethod
    def is_many_to_many_relation(cls, field_name: str) -> bool:
        return cls.is_relation(field_name) and isinstance(
            getattr(cls.get_model(), field_name), related_descriptors.ManyToManyDescriptor
        )

    @classmethod
    def is_primary_key(cls, field_name: str) -> bool:
        class_attr = getattr(cls.get_model(), field_name)

        if class_attr is None:
            return False

        return hasattr(class_attr, "field") and class_attr.field.primary_key

    @classmethod
    def is_immutable(cls) -> bool:
        """
        Return true if this is a visitor for a resource that should never be copied.
        """
        return cls.immutable


"""
Immutable visitors (resources we never want to copy)
"""


class TeamVisitor(ResourceTransferVisitor, kind="Team", immutable=True, user_facing=False):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Team

        return Team


class ProjectVisitor(ResourceTransferVisitor, kind="Project", immutable=True, user_facing=False):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Project

        return Project


class UserVisitor(ResourceTransferVisitor, kind="User", immutable=True, user_facing=False):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import User

        return User


"""
All the other visitors for resources we want to copy.
"""


class DashboardVisitor(
    ResourceTransferVisitor,
    kind="Dashboard",
    excluded_fields=[
        "data_color_theme_id",
        "data_color_theme",
        "analytics_dashboards",
        "last_refresh",
        "last_accessed_at",
        "share_token",
        "is_shared",
    ],
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Dashboard

        return Dashboard


class ActionVisitor(
    ResourceTransferVisitor,
    kind="Action",
    excluded_fields=[
        "is_calculating",
        "last_calculated_at",
        "bytecode",
        "bytecode_error",
        "last_summarized_at",
        "summary",
        "embedding_last_synced_at",
        "embedding_version",
        "events",
        "post_to_slack",
        "slack_message_format",
    ],
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Action

        return Action


class CohortVisitor(
    ResourceTransferVisitor,
    kind="Cohort",
    excluded_fields=[
        "is_calculating",
        "last_calculation",
        "errors_calculating",
        "last_error_at",
        "count",
        "version",
        "pending_version",
        "people",
        "groups",
    ],
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Cohort

        return Cohort


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
            vertex = resource_map.get((target_model, old_pk))
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


class DashboardTileVisitor(
    ResourceTransferVisitor,
    kind="DashboardTile",
    excluded_fields=[
        "filters_hash",
        "last_refresh",
        "refreshing",
        "refresh_attempt",
    ],
    friendly_name="Dashboard tile",
    user_facing=False,
):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import DashboardTile

        return DashboardTile


class TextVisitor(ResourceTransferVisitor, kind="Text", excluded_fields=["last_modified_at"], user_facing=False):
    @classmethod
    def get_model(cls) -> type[models.Model]:
        from posthog.models import Text

        return Text

from typing import Literal
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception

from posthog.schema import AssistantMessageType, AssistantToolCallMessage

from posthog.api.search import ENTITY_MAP, class_queryset
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.utils.types.base import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import ENTITY_TYPE_SUMMARY_TEMPLATE, FOUND_ENTITIES_MESSAGE_TEMPLATE, HYPERLINK_USAGE_INSTRUCTIONS


class EntitySearchNode(BaseAssistantNode[AssistantState, AssistantState]):
    REASONING_MESSAGE = "Searching for entities..."
    MAX_ENTITY_RESULTS = 10

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ENTITY_SEARCH

    @property
    def user_access_control(self) -> UserAccessControl:
        return UserAccessControl(user=self._user, team=self._team, organization_id=self._team.organization.id)

    def build_url(self, result: dict) -> str:
        entity_type = result["type"]
        result_id = result["result_id"]
        base_url = f"/project/{self._team.id}"
        match entity_type:
            case "insight":
                return f"{base_url}/insights/{result_id}"
            case "dashboard":
                return f"{base_url}/dashboard/{result_id}"
            case "experiment":
                return f"{base_url}/experiments/{result_id}"
            case "feature_flag":
                return f"{base_url}/feature_flags/{result_id}"
            case "notebook":
                return f"{base_url}/notebooks/{result_id}"
            case "action":
                return f"{base_url}/data-management/actions/{result_id}"
            case "cohort":
                return f"{base_url}/cohorts/{result_id}"
            case "event_definition":
                return f"{base_url}/data-management/events/{result_id}"
            case "survey":
                return f"{base_url}/surveys/{result_id}"
            case _:
                return f"{base_url}/{entity_type}/{result_id}"

    def _get_formatted_entity_result(self, result: dict) -> list[str]:
        result_summary = []
        entity_type = result["type"]
        result_id = result["result_id"]

        extra_fields = result.get("extra_fields", {})

        name = extra_fields.get("name", f"{entity_type.upper()} {result_id}")
        key = extra_fields.get("key", "")
        description = extra_fields.get("description", "")

        result_summary.append(f"**[{name}]({self.build_url(result)})**")
        if key:
            result_summary.append(f"\n - Key: {key}")
        if description:
            result_summary.append(f"\n - Description: {description}")
        return result_summary

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        """Search for entities by query and optional entity types."""

        query = state.entity_search_query
        if not query:
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="No search query provided.",
                        type=AssistantMessageType.Assistant,
                        tool_call_id=state.root_tool_call_id,
                        id=str(uuid4()),
                    )
                ]
            )

        try:
            entity_types = state.entity_search_types or list(ENTITY_MAP.keys())
            content = ""
            results = []
            counts = {}

            for entity_type in entity_types:
                entity_meta = ENTITY_MAP.get(entity_type)
                if not entity_meta:
                    content += f"Invalid entity type: {entity_type}. Will not search for this entity type."
                    continue
                await self._write_reasoning(f"Searching through the {entity_type}s")
                klass_qs, _ = await database_sync_to_async(class_queryset)(
                    view=self,
                    klass=entity_meta["klass"],
                    project_id=self._team.project_id,
                    query=state.entity_search_query,
                    search_fields=entity_meta["search_fields"],
                    extra_fields=entity_meta["extra_fields"],
                )

                def evaluate_queryset(klass_qs=klass_qs):
                    return list(klass_qs[: self.MAX_ENTITY_RESULTS])

                entity_results = await database_sync_to_async(evaluate_queryset)()

                results.extend(entity_results)
                counts[entity_type] = len(entity_results)

            if results and "rank" in results[0]:
                results.sort(key=lambda x: x.get("rank", 0), reverse=True)

            # Format results for display
            if not results:
                content += f"No entities found matching the query '{state.entity_search_query}' for entity types {entity_types}"
            else:
                result_summary = []
                for result in results:
                    result_summary.extend(self._get_formatted_entity_result(result))

                total_results = len(results)
                content += FOUND_ENTITIES_MESSAGE_TEMPLATE.format(
                    total_results=total_results, entities_list="\n".join(result_summary)
                )

                if counts:
                    content += ENTITY_TYPE_SUMMARY_TEMPLATE.format(
                        entity_type_summary="\n".join(
                            [f"- {entity_type.title()}: {count}" for entity_type, count in counts.items() if count > 0]
                        )
                    )
                content += f"\n\n{HYPERLINK_USAGE_INSTRUCTIONS}"

            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(content=content, tool_call_id=state.root_tool_call_id, id=str(uuid4())),
                ],
                entity_search_query=None,
                entity_search_types=None,
                root_tool_call_id=None,
            )

        except Exception as e:
            capture_exception(
                e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
            )
            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=f"Error searching entities: {str(e)}",
                        tool_call_id=state.root_tool_call_id,
                        id=str(uuid4()),
                    ),
                ],
                entity_search_query=None,
                entity_search_types=None,
                root_tool_call_id=None,
            )

    def router(self, state: AssistantState) -> Literal["root"]:
        return "root"

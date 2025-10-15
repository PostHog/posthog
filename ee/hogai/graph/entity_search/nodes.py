from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception

from posthog.schema import AssistantMessage, AssistantMessageType, AssistantToolCallMessage

from posthog.api.search import ENTITY_MAP, class_queryset
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.utils.types.base import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.composed import MaxNodeName

from .prompts import ENTITY_TYPE_SUMMARY_TEMPLATE, FOUND_ENTITIES_MESSAGE_TEMPLATE, HYPERLINK_USAGE_INSTRUCTIONS


class EntitySearchNode(BaseAssistantNode[AssistantState, AssistantState]):
    REASONING_MESSAGE = "Searching for entities..."

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ENTITY_SEARCH

    @property
    def user_access_control(self) -> UserAccessControl:
        return UserAccessControl(user=self._user, team=self._team)

    def build_url(self, result: dict) -> str:
        entity_type = result["type"]
        result_id = result["result_id"]
        match entity_type:
            case "insight":
                return f"/project/{self._team.id}/insights/{result_id}"
            case "dashboard":
                return f"/project/{self._team.id}/dashboard/{result_id}"
            case "experiment":
                return f"/project/{self._team.id}/experiments/{result_id}"
            case "feature_flag":
                return f"/project/{self._team.id}/feature_flags/{result_id}"
            case "notebook":
                return f"/project/{self._team.id}/notebooks/{result_id}"
            case "action":
                return f"/project/{self._team.id}/data-management/actions/{result_id}"
            case "cohort":
                return f"/project/{self._team.id}/cohorts/{result_id}"
            case "event_definition":
                return f"/project/{self._team.id}/data-management/events/{result_id}"
            case "survey":
                return f"/project/{self._team.id}/surveys/{result_id}"
            case _:
                return f"/project/{self._team.id}/{entity_type}/{result_id}"

    def get_formatted_entity_result(self, result: dict) -> list[str]:
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
                    )
                ]
            )

        try:
            entity_types = state.entity_search_types or list(ENTITY_MAP.keys())

            # Validate entity types
            content = ""
            # Build search results using the existing search infrastructure
            results = []
            counts = {}

            for entity_type in entity_types:
                entity_meta = ENTITY_MAP.get(entity_type)
                if not entity_meta:
                    content += f"Invalid entity type: {entity_type}. Will not search for this entity type."
                    continue
                klass_qs, _ = await database_sync_to_async(class_queryset)(
                    view=self,
                    klass=entity_meta["klass"],
                    project_id=self._team.project_id,
                    query=state.entity_search_query,
                    search_fields=entity_meta["search_fields"],
                    extra_fields=entity_meta["extra_fields"],
                )

                # Get results for this entity type - wrap queryset evaluation
                def evaluate_queryset(klass_qs=klass_qs):
                    return list(klass_qs[:10])

                entity_results = await database_sync_to_async(evaluate_queryset)()

                results.extend(entity_results)
                counts[entity_type] = len(entity_results)

            # Sort by rank if we have search results
            if results and "rank" in results[0]:
                results.sort(key=lambda x: x.get("rank", 0), reverse=True)

            # Format results for display
            if not results:
                content += (
                    f"\n\n No entities found matching '{state.entity_search_query}' for entity types {entity_type}"
                )
            else:
                # Create a summary of results
                result_summary = []
                for result in results:
                    # Format the result based on entity type
                    result_summary.extend(self.get_formatted_entity_result(result))

                # Create summary text
                total_results = len(results)
                content += FOUND_ENTITIES_MESSAGE_TEMPLATE.format(
                    total_results=total_results, entities_list="\n".join(result_summary)
                )

                # Add counts summary
                if counts:
                    content += ENTITY_TYPE_SUMMARY_TEMPLATE.format(
                        entity_type_summary="\n".join(
                            [f"- {entity_type.title()}: {count}" for entity_type, count in counts.items() if count > 0]
                        )
                    )
                content += f"\n\n{HYPERLINK_USAGE_INSTRUCTIONS}"

            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=content,
                        tool_call_id=state.root_tool_call_id,
                        visible=True,
                    ),
                ]
            )

        except Exception as e:
            capture_exception(
                e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
            )
            return PartialAssistantState(messages=[AssistantMessage(content=f"Error searching entities: {str(e)}")])

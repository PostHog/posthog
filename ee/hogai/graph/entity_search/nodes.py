from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception

from posthog.schema import AssistantMessage, AssistantMessageType

from posthog.api.search import ENTITY_MAP, class_queryset
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from ee.hogai.graph.base import BaseAssistantNode
from ee.hogai.utils.types.base import AssistantNodeName, AssistantState, PartialAssistantState
from ee.hogai.utils.types.composed import MaxNodeName


class EntitySearchNode(BaseAssistantNode[AssistantState, AssistantState]):
    REASONING_MESSAGE = "Searching for entities..."

    @property
    def node_name(self) -> MaxNodeName:
        return AssistantNodeName.ENTITY_SEARCH

    @property
    def user_access_control(self) -> UserAccessControl:
        return UserAccessControl(user=self._user, team=self._team)

    async def arun(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState:
        """Search for entities by query and optional entity types."""

        query = state.entity_search_query
        if not query:
            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content="No search query provided.",
                        type=AssistantMessageType.Assistant,
                    )
                ]
            )

        try:
            entity_types = state.entity_search_types or list(ENTITY_MAP.keys())

            # Validate entity types
            invalid_types = [t for t in entity_types if t not in ENTITY_MAP]
            if invalid_types:
                return PartialAssistantState(
                    messages=[
                        AssistantMessage(
                            content=f"Invalid entity types: {', '.join(invalid_types)}. Available types: {', '.join(ENTITY_MAP.keys())}"
                        )
                    ]
                )

            # Build search results using the existing search infrastructure
            results = []
            counts = {}

            for entity_type in entity_types:
                entity_meta = ENTITY_MAP[entity_type]
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
                content = f"No entities found matching '{state.entity_search_query}'"
            else:
                # Create a summary of results
                result_summary = []
                for result in results:
                    entity_type = result["type"]
                    result_id = result["result_id"]
                    extra_fields = result.get("extra_fields", {})

                    # Format the result based on entity type
                    if entity_type == "insight":
                        name = extra_fields.get("name", f"Insight {result_id}")
                        description = extra_fields.get("description", "")
                        result_summary.append(f"📊 **{name}** (Insight {result_id})")
                        if description:
                            result_summary.append(f"   {description}")
                    elif entity_type == "dashboard":
                        name = extra_fields.get("name", f"Dashboard {result_id}")
                        description = extra_fields.get("description", "")
                        result_summary.append(f"📋 **{name}** (Dashboard {result_id})")
                        if description:
                            result_summary.append(f"   {description}")
                    elif entity_type == "cohort":
                        name = extra_fields.get("name", f"Cohort {result_id}")
                        description = extra_fields.get("description", "")
                        result_summary.append(f"👥 **{name}** (Cohort {result_id})")
                        if description:
                            result_summary.append(f"   {description}")
                    elif entity_type == "action":
                        name = extra_fields.get("name", f"Action {result_id}")
                        description = extra_fields.get("description", "")
                        result_summary.append(f"⚡ **{name}** (Action {result_id})")
                        if description:
                            result_summary.append(f"   {description}")
                    elif entity_type == "experiment":
                        name = extra_fields.get("name", f"Experiment {result_id}")
                        description = extra_fields.get("description", "")
                        result_summary.append(f"🧪 **{name}** (Experiment {result_id})")
                        if description:
                            result_summary.append(f"   {description}")
                    elif entity_type == "feature_flag":
                        key = extra_fields.get("key", f"Flag {result_id}")
                        name = extra_fields.get("name", "")
                        result_summary.append(f"🚩 **{key}** (Feature Flag {result_id})")
                        if name:
                            result_summary.append(f"   {name}")
                    elif entity_type == "notebook":
                        title = extra_fields.get("title", f"Notebook {result_id}")
                        result_summary.append(f"📝 **{title}** (Notebook {result_id})")
                    elif entity_type == "survey":
                        name = extra_fields.get("name", f"Survey {result_id}")
                        description = extra_fields.get("description", "")
                        result_summary.append(f"📋 **{name}** (Survey {result_id})")
                        if description:
                            result_summary.append(f"   {description}")
                    elif entity_type == "event_definition":
                        name = extra_fields.get("name", f"Event {result_id}")
                        result_summary.append(f"📈 **{name}** (Event Definition {result_id})")

                    result_summary.append("")  # Add spacing between results

                # Create summary text
                total_results = len(results)
                content = f"Found {total_results} entities matching the user's query\n\n"
                content += "\n".join(result_summary)

                # Add counts summary
                if counts:
                    content += f"\n\n**Results by type:**\n"
                    for entity_type, count in counts.items():
                        if count > 0:
                            content += f"- {entity_type.title()}: {count}\n"

            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content=content,
                    )
                ]
            )

        except Exception as e:
            capture_exception(
                e, distinct_id=self._get_user_distinct_id(config), properties=self._get_debug_props(config)
            )
            return PartialAssistantState(messages=[AssistantMessage(content=f"Error searching entities: {str(e)}")])

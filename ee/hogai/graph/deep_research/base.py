from ee.hogai.graph.base import AssistantNode
from ee.hogai.utils.types import DeepResearchPlanWithResults
from langchain_core.runnables import RunnableConfig
import xml.etree.ElementTree as ET


class DeepResearchNode(AssistantNode):
    async def _save_deep_research_plan(
        self, deep_research_plan: DeepResearchPlanWithResults, config: RunnableConfig
    ) -> None:
        trace_id = self._get_trace_id(config)
        if trace_id:
            conversation = await self._aget_conversation(trace_id)
            if conversation:
                conversation.deep_research_plan = deep_research_plan.model_dump()
                await conversation.asave()

    def _format_plan_xml(self, plan: DeepResearchPlanWithResults) -> str:
        root = ET.Element("TO-DOs")
        for todo in plan.todos:
            todo_tag = ET.SubElement(root, "todo")
            id_tag = ET.SubElement(todo_tag, "short_id")
            id_tag.text = str(todo.short_id)
            name_tag = ET.SubElement(todo_tag, "short_description")
            name_tag.text = todo.short_description
            instructions_tag = ET.SubElement(todo_tag, "instructions")
            instructions_tag.text = todo.instructions
            status_tag = ET.SubElement(todo_tag, "status")
            status_tag.text = todo.status
            requires_result_from_previous_todo_tag = ET.SubElement(todo_tag, "requires_result_from_previous_todo")
            requires_result_from_previous_todo_tag.text = str(todo.requires_result_from_previous_todo)
            result_tag = ET.SubElement(todo_tag, "result")
            result = plan.results.get(todo.short_id, None)
            if result:
                result_tag.text = result

        return ET.tostring(root, encoding="unicode")

    def _format_plan_string(self, plan: DeepResearchPlanWithResults) -> str:
        return "\n".join(
            [("- ✅ " if todo.status == "completed" else "- ") + f"{todo.short_description}" for todo in plan.todos]
        )

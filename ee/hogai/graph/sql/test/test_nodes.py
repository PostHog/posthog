from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from ee.hogai.graph.sql.nodes import SQLGeneratorNode, SQLPlannerNode
from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantHogQLQuery,
    HumanMessage,
    DatabaseSchemaPostHogTable,
    VisualizationMessage,
    DatabaseSerializedFieldType,
    DatabaseSchemaField,
    DatabaseSchemaManagedViewTable,
    DatabaseSchemaManagedViewTableKind,
)
from posthog.test.base import BaseTest


def deindent(text: str) -> str:
    lines = text.strip("\n").split("\n")

    # Count how many leading spaces are in the first line
    leading_spaces = len(lines[0]) - len(lines[0].lstrip())

    # Strip leading spaces from each line
    return "\n".join(line[leading_spaces:] for line in lines).strip()


class TestSQLPlannerNode(BaseTest):
    def test_sql_planner_prompt_has_tools(self):
        node = SQLPlannerNode(self.team)
        with patch.object(SQLPlannerNode, "_model") as model_mock:

            def assert_prompt(prompt):
                self.assertIn("retrieve_event_properties", str(prompt))
                return AIMessage(content="Thought.\nAction: abc")

            model_mock.return_value = RunnableLambda(assert_prompt)
            node.run(AssistantState(messages=[HumanMessage(content="Text")]), {})


class TestSQLGeneratorNode(BaseTest):
    maxDiff = None

    def test_node_runs(self):
        node = SQLGeneratorNode(self.team)
        with patch.object(SQLGeneratorNode, "_model") as generator_model_mock:
            answer = AssistantHogQLQuery(query="SELECT 1")
            generator_model_mock.return_value = RunnableLambda(lambda _: answer.model_dump())
            new_state = node.run(
                AssistantState(
                    messages=[HumanMessage(content="Text")],
                    plan="Plan",
                    root_tool_insight_plan="question",
                ),
                {},
            )

            assert new_state == PartialAssistantState(
                messages=[
                    VisualizationMessage(
                        query="question",
                        answer=answer,
                        plan="Plan",
                        id=new_state.messages[0].id if new_state.messages else None,
                    )
                ],
                intermediate_steps=[],
                plan="",
            )

    def test_schema_description_for_table_basic(self):
        node = SQLGeneratorNode(self.team)
        table = DatabaseSchemaPostHogTable(
            id="test_table",
            name="test_table",
            fields={
                "id": DatabaseSchemaField(
                    name="id", type=DatabaseSerializedFieldType.INTEGER, hogql_value="id", schema_valid=True
                ),
                "name": DatabaseSchemaField(
                    name="name", type=DatabaseSerializedFieldType.STRING, hogql_value="name", schema_valid=True
                ),
            },
        )

        result = node._schema_description_for_table("test_table", table)

        expected = """
            Table `test_table`
            Fields:
            - id (integer)
            - name (string)
        """

        self.assertEqual(result, deindent(expected))

    def test_schema_description_for_table_with_description(self):
        node = SQLGeneratorNode(self.team)
        table = DatabaseSchemaManagedViewTable(
            id="revenue_charges",
            name="revenue_charges",
            fields={
                "customer_id": DatabaseSchemaField(
                    name="customer_id",
                    type=DatabaseSerializedFieldType.STRING,
                    hogql_value="customer_id",
                    schema_valid=True,
                ),
                "amount": DatabaseSchemaField(
                    name="amount", type=DatabaseSerializedFieldType.DECIMAL, hogql_value="amount", schema_valid=True
                ),
            },
            query={"query": "SELECT * FROM anything"},  # Not used for schema description
            kind=DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE,
        )

        result = node._schema_description_for_table("revenue_charges", table)

        expected = """
            Table `revenue_charges`
            When to use this table: Useful for Revenue-related questions, contains charges for customers
            Fields:
            - customer_id (string)
            - amount (decimal)
        """

        self.assertEqual(result, deindent(expected))

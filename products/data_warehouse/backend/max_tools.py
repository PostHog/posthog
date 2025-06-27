from typing import Optional
from ee.hogai.tool import MaxTool
from pydantic import BaseModel, Field
from products.data_warehouse.backend.prompts import SQL_ASSISTANT_ROOT_SYSTEM_PROMPT
from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.hogql.context import HogQLContext
from posthog.hogql.ai import HOGQL_EXAMPLE_MESSAGE, IDENTITY_MESSAGE, SCHEMA_MESSAGE
from ee.hogai.graph.sql.toolkit import SQL_SCHEMA
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from ee.hogai.graph.schema_generator.utils import SchemaGeneratorOutput

from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast


class HogQLGeneratorArgs(BaseModel):
    instructions: str = Field(description="The instructions for what query to generate.")


class HogQLGeneratorTool(MaxTool):
    name: str = "generate_hogql_query"
    description: str = (
        "Write or edit an SQL query to answer the user's question, and apply it to the current SQL editor"
    )
    thinking_message: str = "Coming up with an SQL query"
    args_schema: type[BaseModel] = HogQLGeneratorArgs
    root_system_prompt_template: str = SQL_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self, instructions: str) -> tuple[str, str]:
        database = create_hogql_database(team=self._team)
        hogql_context = HogQLContext(team=self._team, enable_select_queries=True, database=database)

        serialized_database = serialize_database(hogql_context)
        schema_description = "\n\n".join(
            (
                f"Table `{table_name}` with fields:\n"
                + "\n".join(f"- {field.name} ({field.type})" for field in table.fields.values())
                for table_name, table in serialized_database.items()
                # Only the most important core tables, plus all warehouse tables
                if table_name in ["events", "groups", "persons"]
                or table_name in database.get_warehouse_tables()
                or table_name in database.get_views()
            )
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    IDENTITY_MESSAGE
                    + "\n\n<example_query>\n"
                    + HOGQL_EXAMPLE_MESSAGE
                    + "\n</example_query>\n\n"
                    + SCHEMA_MESSAGE.format(schema_description=schema_description)
                    + "\n\n<current_query>\n{{{current_query}}}\n</current_query>",
                ),
                ("user", "Write a new HogQL query or tweak the current one to satisfy this request: " + instructions),
            ],
            template_format="mustache",
        )

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                chain = prompt | self._model
                result = chain.invoke(self.context)
                parsed_result = self._parse_output(result, hogql_context)
                break
            except PydanticOutputParserException as e:
                prompt += f"Avoid this error: {str(e)}"
                final_error = e
        else:
            raise final_error

        return "```sql\n" + parsed_result + "\n```", parsed_result

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1", temperature=0.3, disable_streaming=True).with_structured_output(
            SQL_SCHEMA,
            method="function_calling",
            include_raw=False,
        )

    def _parse_output(self, output, hogql_context: HogQLContext):  # type: ignore
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        # We also ensure the generated SQL is valid
        assert result.query is not None
        try:
            print_ast(parse_select(result.query), context=hogql_context, dialect="clickhouse")
        except (ExposedHogQLError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = f'This is not valid parsable SQL! The last 5 characters where we tripped up were "{result.query[-5:]}".'
            raise PydanticOutputParserException(llm_output=result.query, validation_message=err_msg)
        except Exception as e:
            raise PydanticOutputParserException(llm_output=result.query, validation_message=str(e))
        return result.query

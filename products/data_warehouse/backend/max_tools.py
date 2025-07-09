import asyncio
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from ee.hogai.graph.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.graph.sql.toolkit import SQL_SCHEMA
from ee.hogai.tool import MaxTool
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, create_hogql_database, serialize_database
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.sync import database_sync_to_async
from products.data_warehouse.backend.prompts import (
    HOGQL_GENERATOR_SYSTEM_PROMPT,
    HOGQL_GENERATOR_USER_PROMPT,
    SQL_ASSISTANT_ROOT_SYSTEM_PROMPT,
)


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

    async def _arun_impl(self, instructions: str) -> tuple[str, str]:
        database = await database_sync_to_async(create_hogql_database)(team=self._team)
        hogql_context = HogQLContext(team=self._team, enable_select_queries=True, database=database)

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", HOGQL_GENERATOR_SYSTEM_PROMPT),
                ("user", HOGQL_GENERATOR_USER_PROMPT),
            ],
            template_format="mustache",
        )

        schema_description, core_memory = await asyncio.gather(
            self._get_database_schema(database, hogql_context),
            self._aget_core_memory_text(self._team),
        )

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                chain = prompt | self._model
                result = await chain.ainvoke(
                    {
                        **self.context,
                        "schema_description": schema_description,
                        "core_memory": core_memory,
                        "instructions": instructions,
                    }
                )
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

    @database_sync_to_async
    def _get_database_schema(self, database: Database, hogql_context: HogQLContext):
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
        return schema_description

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

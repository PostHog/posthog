from typing import Optional

from langchain_core.messages import (
    merge_message_runs,
)
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from ee.hogai.graph.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.graph.sql.mixins import HogQLGeneratorMixin
from ee.hogai.graph.sql.toolkit import SQL_SCHEMA
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool
from products.data_warehouse.backend.prompts import (
    HOGQL_GENERATOR_USER_PROMPT,
    HOGQL_INJECTED_QUERY_PROMPT,
    SQL_ASSISTANT_ROOT_SYSTEM_PROMPT,
)


class HogQLGeneratorArgs(BaseModel):
    instructions: str = Field(description="The instructions for what query to generate.")


class HogQLGeneratorTool(HogQLGeneratorMixin, MaxTool):
    name: str = "generate_hogql_query"
    description: str = (
        "Write or edit an SQL query to answer the user's question, and apply it to the current SQL editor"
    )
    thinking_message: str = "Coming up with an SQL query"
    args_schema: type[BaseModel] = HogQLGeneratorArgs
    root_system_prompt_template: str = SQL_ASSISTANT_ROOT_SYSTEM_PROMPT

    async def _arun_impl(self, instructions: str) -> tuple[str, str]:
        system_prompt = await self._construct_system_prompt()

        prompt = system_prompt + ChatPromptTemplate.from_messages(
            [
                ("system", HOGQL_INJECTED_QUERY_PROMPT),
                ("user", HOGQL_GENERATOR_USER_PROMPT),
            ],
            template_format="mustache",
        )

        final_error: Optional[Exception] = None
        for _ in range(3):
            try:
                chain = prompt | merge_message_runs | self._model | self._parse_output
                result: str = await chain.ainvoke(
                    {
                        **self.context,
                        "instructions": instructions,
                    }
                )
                break
            except PydanticOutputParserException as e:
                prompt += f"Avoid this error: {str(e)}"
                final_error = e
        else:
            assert final_error is not None
            raise final_error

        return "```sql\n" + result + "\n```", result

    @property
    def _model(self):
        return MaxChatOpenAI(
            user=self._user, team=self._team, model="gpt-4.1", temperature=0.3, disable_streaming=True
        ).with_structured_output(SQL_SCHEMA, method="function_calling", include_raw=False)

    async def _parse_output(self, output: dict) -> str:
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        database = await self._get_database()
        hogql_context = self._get_default_hogql_context(database)
        query = await self._parse_generated_hogql(result.query, hogql_context)
        return query

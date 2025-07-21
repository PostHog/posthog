import asyncio

from langchain_core.prompts import ChatPromptTemplate

from ee.hogai.graph.mixins import AssistantContextMixin
from ee.hogai.utils.warehouse import serialize_database_schema
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database, create_hogql_database
from posthog.hogql.errors import ExposedHogQLError, NotImplementedError as HogQLNotImplementedError, ResolutionError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from posthog.sync import database_sync_to_async

from ..schema_generator.parsers import PydanticOutputParserException
from .prompts import HOGQL_GENERATOR_SYSTEM_PROMPT


class HogQLGeneratorMixin(AssistantContextMixin):
    _database_instance: Database | None = None

    async def _get_database(self):
        if self._database_instance:
            return self._database_instance
        self._database_instance = await database_sync_to_async(create_hogql_database)(team=self._team)
        return self._database_instance

    def _get_default_hogql_context(self, database: Database):
        hogql_context = HogQLContext(team=self._team, database=database, enable_select_queries=True)
        return hogql_context

    async def _construct_system_prompt(self) -> ChatPromptTemplate:
        database = await self._get_database()
        hogql_context = self._get_default_hogql_context(database)

        schema_description, core_memory = await asyncio.gather(
            serialize_database_schema(database, hogql_context),
            self._aget_core_memory_text(),
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", HOGQL_GENERATOR_SYSTEM_PROMPT),
            ],
            template_format="mustache",
        ).partial(schema_description=schema_description, core_memory=core_memory)

        return prompt

    @database_sync_to_async(thread_sensitive=False)
    def _parse_generated_hogql(self, query: str | None, hogql_context: HogQLContext):
        if query is None:
            raise PydanticOutputParserException(llm_output="", validation_message="Output is empty")
        try:
            print_ast(parse_select(query), context=hogql_context, dialect="clickhouse")
        except (ExposedHogQLError, HogQLNotImplementedError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = (
                    f'This is not valid parsable SQL! The last 5 characters where we tripped up were "{query[-5:]}".'
                )
            raise PydanticOutputParserException(llm_output=query, validation_message=err_msg)
        except Exception as e:
            raise PydanticOutputParserException(llm_output=query, validation_message=str(e))
        return query

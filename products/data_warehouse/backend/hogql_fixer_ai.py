import os
from ee.hogai.tool import MaxTool
from posthog.hogql.database.database import create_hogql_database, serialize_database
from posthog.hogql.context import HogQLContext
from ee.hogai.graph.sql.toolkit import SQL_SCHEMA
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from ee.hogai.graph.schema_generator.utils import SchemaGeneratorOutput

from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast


_parser_contents: str | None = None
_lexer_contents: str | None = None


def get_parser_contents() -> str:
    global _parser_contents

    if _parser_contents is not None:
        return _parser_contents

    with open(f"{os.getcwd()}/posthog/hogql/grammar/HogQLParser.g4") as parser_file:
        _parser_contents = parser_file.read()

    return _parser_contents


def get_lexer_contents() -> str:
    global _lexer_contents

    if _lexer_contents is not None:
        return _lexer_contents

    with open(f"{os.getcwd()}/posthog/hogql/grammar/HogQLLexer.g4") as parser_file:
        _lexer_contents = parser_file.read()

    return _lexer_contents


SQL_ASSISTANT_ROOT_SYSTEM_PROMPT = """
The user has written a HogQL query which contains error. They expect your help with tweaking the HogQL to fix these errors.

IMPORTANT: This is currently your primary task. Therefore `fix_hogql_query` is currently your primary tool.
Use `fix_hogql_query` when fixing any errors remotely related to HogQL.
It's very important to disregard other tools for these purposes - the user expects `fix_hogql_query`.

NOTE: When calling the `fix_hogql_query` tool, do not provide any response other than the tool call.
"""

SYSTEM_PROMPT = f"""
HogQL is PostHog's variant of SQL. HogQL is a transpiler that outputs Clickhouse SQL. We use Antlr4 to define the HogQL language.
Below is the antlr parser and lexer definitions - when writing HogQL, ensure you follow the grammar rules.

<hogql_parser>
{get_parser_contents()}
</hogql_parser>

<hogql_lexer>
{get_lexer_contents()}
</hogql_lexer>

You fix HogQL errors that may come from either HogQL resolver errors or clickhouse execution errors. You don't help with other knowledge.

Important HogQL differences versus other SQL dialects:
- JSON properties are accessed like `properties.foo.bar` instead of `properties->foo->bar`

This is the schema of tables available in queries:

{{schema_description}}

Person or event metadata unspecified above (emails, names, etc.) is stored in `properties` fields, accessed like: `properties.foo.bar`.
Note: "persons" means "users" here - instead of a "users" table, we have a "persons" table.

Standardized events/properties such as pageview or screen start with `$`. Custom events/properties start with any other character.

`virtual_table` and `lazy_table` fields are connections to linked tables, e.g. the virtual table field `person` allows accessing person properties like so: `person.properties.foo`.
""".strip()

USER_PROMPT = """
Fix the errors in the HogQL query below and only return the new updated query in your response.

- Don't update any other part of the query if it's not relevant to the error, including rewriting shorthand clickhouse SQL to the full version.
- Don't change the capitalisation of the query if it's not relevant to the error, such as rewriting `select` as `SELECT` or `from` as `FROM`
- There may also be more than one error in the syntax.

Below is the current HogQL query and the error message
"""


class HogQLQueryFixerTool(MaxTool):
    name: str = "fix_hogql_query"
    description: str = "Fixes any error in the current HogQL query"
    thinking_message: str = "Fixing errors in the SQL query"
    root_system_prompt_template: str = SQL_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self) -> tuple[str, str | None]:
        database = create_hogql_database(self._team_id)
        hogql_context = HogQLContext(team_id=self._team_id, enable_select_queries=True, database=database)

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
                    SYSTEM_PROMPT.replace("{{schema_description}}", schema_description),
                ),
                (
                    "user",
                    USER_PROMPT
                    + "\n\n<hogql_query>"
                    + "{{{hogql_query}}}"
                    + "</hogql_query>"
                    + "\n\n<error>"
                    + "{{{error_message}}}"
                    + "</error>",
                ),
            ],
            template_format="mustache",
        )

        for i in range(3):
            try:
                chain = prompt | self._model
                result = chain.invoke(self.context)
                parsed_result = self._parse_output(result, hogql_context)
                break
            except PydanticOutputParserException as e:
                prompt += f"\n\nWe've ran this prompt {i+1} time{'s' if i+1 > 1 else ''} now. The newly updated query gave us this error: {e.validation_message}"
        else:
            return "", None

        return parsed_result, parsed_result

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4o", temperature=0, disable_streaming=True).with_structured_output(
            SQL_SCHEMA,
            method="function_calling",
            include_raw=False,
        )

    def _parse_output(self, output, hogql_context: HogQLContext):
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        # We also ensure the generated SQL is valid
        assert result.query is not None
        try:
            print_ast(parse_select(result.query), context=hogql_context, dialect="clickhouse")
        except (ExposedHogQLError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = f'ANTLR parsing error: "no viable alternative at input". This means that the query isn\' valid HogQL. The last 5 characters where we tripped up were "{result.query[-5:]}".'
            raise PydanticOutputParserException(llm_output=result.query, validation_message=err_msg)
        except Exception as e:
            raise PydanticOutputParserException(llm_output=result.query, validation_message=str(e))

        return result.query

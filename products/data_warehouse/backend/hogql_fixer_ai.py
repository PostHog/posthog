from typing import Any

from langchain.schema import HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.functions.mapping import HOGQL_AGGREGATIONS, HOGQL_CLICKHOUSE_FUNCTIONS, HOGQL_POSTHOG_FUNCTIONS
from posthog.hogql.metadata import get_table_names
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from ee.hogai.graph.schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from ee.hogai.graph.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.graph.sql.toolkit import SQL_SCHEMA
from ee.hogai.tool import MaxTool

_hogql_functions: str | None = None


def get_hogql_functions() -> str:
    global _hogql_functions

    if _hogql_functions is not None:
        return _hogql_functions

    ch_functions = list(HOGQL_CLICKHOUSE_FUNCTIONS.keys())
    ch_aggregations = list(HOGQL_AGGREGATIONS.keys())
    ph_functions = list(HOGQL_POSTHOG_FUNCTIONS.keys())

    _hogql_functions = f"""HogQL defines what functions are available with most (but not all) having a 1:1 mapping to ClickHouse functions.
These are the non-aggregated HogQL functions:
```
{str(ch_functions)}
```

These are the aggregated HogQL functions:
```
{str(ch_aggregations)}
```

And lastly these are some HogQL specific functions:
```
{str(ph_functions)}
```"""

    return _hogql_functions


SQL_ASSISTANT_ROOT_SYSTEM_PROMPT = """
You are a senior software engineer with deep expertise in SQL, specifically in the HogQL dialect.
Your job is to help users fix invalid or broken HogQL queries by identifying the errors and returning a corrected version of the query.

IMPORTANT: This is currently your primary task. Therefore `fix_hogql_query` is currently your primary tool.
Use `fix_hogql_query` when fixing any errors remotely related to HogQL.
It's very important to disregard other tools for these purposes - the user expects `fix_hogql_query`.

NOTE: When calling the `fix_hogql_query` tool, do not provide any response other than the tool call.
"""

SYSTEM_PROMPT = f"""
HogQL is PostHog's variant of SQL. HogQL is based on Clickhouse SQL with a few small adjustments.

{get_hogql_functions()}

You fix HogQL errors that may come from either HogQL resolver errors or clickhouse execution errors. You don't help with other knowledge.

Important HogQL differences versus other SQL dialects:
- JSON properties are accessed like `properties.foo.bar` instead of `properties->foo->bar`
- Queries can have pre-defined variables denoted by `{{variable_name}}`
- Only `SELECT` queries can be written in HogQL - so no `INSERT` or `UPDATE` for example
- HogQL supports the comparison operator `IN COHORT` and `NOT IN COHORT` to check whether persons are within a cohort or not. A cohort can be defined by id or string name
- `virtual_table` and `lazy_table` fields are connections to linked tables, e.g. the virtual table field `person` allows accessing person properties like so: `person.properties.foo`.
- Standardized events/properties such as pageview or screen start with `$`. Custom events/properties start with any other character.
- HogQL statements should not end with a semi-colon - this is invalid syntax

HogQL examples:
Invalid: SELECT * FROM events WHERE properties->foo = 'bar'
Valid: SELECT * FROM events WHERE properties.foo = 'bar'

Invalid: SELECT user_id FROM persons
Valid: SELECT id FROM persons

Invalid: SELECT * FROM persons;
Valid: SELECT * FROM persons

Bad Query: SELECT * FROM events WHERE properties->foo = 'bar'
Error: Unexpected '->'
Fixed Query: SELECT * FROM events WHERE properties.foo = 'bar'

Example 2:
Bad Query: SELECT COUNT(user_id) FROM persons
Error: No column 'user_id'
Fixed Query: SELECT COUNT(id) FROM persons

This is a list of all the available tables in the database:
```
{{{{all_table_names}}}}
```

`person` or `event` metadata unspecified above (emails, names, etc.) is stored in `properties` fields, accessed like: `properties.foo.bar`.
Note: "persons" means "users" here - instead of a "users" table, we have a "persons" table.


""".strip()

USER_PROMPT = """
Fix the errors in the HogQL query below and only return the new updated query in your response.

- Don't update any other part of the query if it's not relevant to the error, including rewriting shorthand clickhouse SQL to the full version.
- Don't change the capitalisation of the query if it's not relevant to the error, such as rewriting `select` as `SELECT` or `from` as `FROM`
- Don't convert syntax to an alternative if it's not relevant to the error, such as changing `toIntervalDay(1)` to `INTERVAL 1 DAY`
- There may also be more than one error in the syntax.

{{schema_description}}

Below is the current HogQL query and the error message
"""


def _get_schema_description(ai_context: dict[Any, Any], hogql_context: HogQLContext, database: Database) -> str:
    serialized_database = database.serialize(hogql_context)
    schema_description = ""

    try:
        query = ai_context.get("hogql_query", None)
        if not query:
            # Dummy exception to get into the except block
            raise Exception()

        select = parse_select(query)
        tables_in_query = get_table_names(select)
        table_fields_str = ""

        for table_name in tables_in_query:
            serialized_table = serialized_database.get(table_name, None)
            if serialized_table:
                table_fields_str = table_fields_str + f"Table `{table_name}` with fields:\n"
                table_fields_str = table_fields_str + "\n".join(
                    f"- {field.name} ({field.type})" for field in serialized_table.fields.values()
                )

        if len(table_fields_str) != 0:
            schema_description = (
                "This is the schema of tables currently used in the provided query:\n\n" + table_fields_str
            )
    except:
        schema_description = "This is the schema of all tables available to the provided query:\n\n" + "\n\n".join(
            (
                f"Table `{table_name}` with fields:\n"
                + "\n".join(f"- {field.name} ({field.type})" for field in table.fields.values())
                for table_name, table in serialized_database.items()
                # Only the most important core tables, plus all warehouse tables
                if table_name in ["events", "groups", "persons"]
                or table_name in database.get_warehouse_table_names()
                or table_name in database.get_view_names()
            )
        )

    return schema_description


def _get_system_prompt(all_tables: list[str]) -> str:
    return SYSTEM_PROMPT.replace("{{all_table_names}}", str(all_tables))


def _get_user_prompt(schema_description: str) -> str:
    return (
        USER_PROMPT.replace("{{schema_description}}", schema_description)
        + "\n\n<hogql_query>"
        + "{{{hogql_query}}}"
        + "</hogql_query>"
        + "\n\n<error>"
        + "{{{error_message}}}"
        + "</error>"
    )


class HogQLQueryFixerTool(MaxTool):
    name: str = "fix_hogql_query"
    description: str = "Fixes any error in the current HogQL query"
    context_prompt_template: str = SQL_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self) -> tuple[str, str | None]:
        database = Database.create_for(team=self._team)
        hogql_context = HogQLContext(team=self._team, enable_select_queries=True, database=database)

        all_table_names = database.get_all_table_names()
        schema_description = _get_schema_description(self.context, hogql_context, database)

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    _get_system_prompt(all_table_names),
                ),
                (
                    "user",
                    _get_user_prompt(schema_description),
                ),
            ],
            template_format="mustache",
        )
        messages = prompt.format_messages(**self.context)

        for _ in range(3):
            try:
                result = self._model.invoke(messages)
                parsed_result = self._parse_output(result, hogql_context)
                break
            except PydanticOutputParserException as e:
                messages.append(
                    HumanMessage(
                        content=f"""
We got another error after the previous message.

Here is the updated query:
<hogql_query>
{e.llm_output}
</hogql_query>

The newly updated query gave us this error:
<error>
{e.validation_message}
</error>""".strip()
                    )
                )
        else:
            return "", None

        return parsed_result, parsed_result

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1", temperature=0, disable_streaming=True).with_structured_output(
            SQL_SCHEMA,
            method="function_calling",
            include_raw=False,
        )

    def _parse_output(self, output, hogql_context: HogQLContext):
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(output)  # type: ignore
        # We also ensure the generated SQL is valid
        assert result.query is not None
        try:
            result.query = result.query.rstrip(";").strip()
            prepare_and_print_ast(parse_select(result.query), context=hogql_context, dialect="clickhouse")
        except (ExposedHogQLError, ResolutionError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                # The "no viable alternative" ANTLR error is horribly unhelpful, both for humans and LLMs
                err_msg = 'ANTLR parsing error: "no viable alternative at input". This means that the query isn\'t valid HogQL.'
            raise PydanticOutputParserException(llm_output=result.query, validation_message=err_msg)

        return result.query

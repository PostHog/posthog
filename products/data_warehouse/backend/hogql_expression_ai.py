import re

from langchain.schema import HumanMessage
from langchain_core.prompts import ChatPromptTemplate

from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import ExposedHogQLError, ResolutionError
from posthog.hogql.parser import parse_expr

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException, parse_pydantic_structured_output
from ee.hogai.chat_agent.schema_generator.utils import SchemaGeneratorOutput
from ee.hogai.llm import MaxChatOpenAI
from ee.hogai.tool import MaxTool

from .hogql_fixer_ai import get_hogql_functions

EXPRESSION_SCHEMA = {
    "name": "output_hogql_expression",
    "description": "Outputs the final HogQL expression",
    "parameters": {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "The HogQL expression to use as a breakdown, filter, or column",
            },
        },
        "additionalProperties": False,
        "required": ["expression"],
    },
}


EXPRESSION_ASSISTANT_ROOT_SYSTEM_PROMPT = """
You are a senior software engineer with deep expertise in SQL, specifically in the HogQL dialect.
Your job is to help users write and refine short HogQL **expressions** (not full SELECT queries)
that can be used as breakdowns, filters, or computed columns in the PostHog UI.

IMPORTANT: This is currently your primary task. Therefore `write_hogql_expression` is currently your primary tool.
Use `write_hogql_expression` for any request related to authoring or refining a HogQL expression.
It's very important to disregard other SQL tools for these purposes - the user expects `write_hogql_expression`.

NOTE: When calling the `write_hogql_expression` tool, do not provide any response other than the tool call.
"""

SYSTEM_PROMPT = f"""
HogQL is PostHog's variant of SQL. HogQL is based on ClickHouse SQL with a few small adjustments.

{get_hogql_functions()}

You help users write short HogQL **expressions** that are used inside the PostHog UI - as breakdowns,
filters, or computed columns. You do not write full SELECT statements here, only the inner expression.

Important HogQL differences versus other SQL dialects:
- JSON properties are accessed like `properties.foo.bar` instead of `properties->foo->bar`
- `virtual_table` and `lazy_table` fields are connections to linked tables, e.g. the virtual table field `person`
  allows accessing person properties like so: `person.properties.foo`.
- Standardized events/properties such as pageview or screen start with `$`. Custom events/properties start with any other character.
- The expression you return MUST be a single HogQL expression (no `SELECT`, no semicolons, no comments
  except an optional trailing `-- column_name` label or `AS column_name` alias).
- Optionally end the expression with `AS column_name` or `-- column_name` to give the breakdown a readable label.

Good HogQL expression examples:
- `properties.$current_url`
- `person.properties.email`
- `toInt(properties.`Long Field Name`) * 10`
- `concat(event, ' ', distinct_id)`
- `toBool(is_identified) ? 'user' : 'anon'`
- `if(properties.$browser = 'Chrome', 'chrome', 'other') AS browser_group`
""".strip()

USER_PROMPT = """
Write or refine a HogQL expression based on the request below. Return ONLY the expression - no
explanation, no surrounding query, no `SELECT`.

The current expression (which CAN be empty when the user is starting fresh) is:
<current_expression>
{{{current_expression}}}
</current_expression>

The user's request is:
<request>
{{{user_request}}}
</request>
""".strip()


class HogQLExpressionWriterTool(MaxTool):
    name: str = "write_hogql_expression"
    description: str = "Writes or refines a short HogQL expression for use as a breakdown, filter, or computed column"
    context_prompt_template: str = EXPRESSION_ASSISTANT_ROOT_SYSTEM_PROMPT

    def _run_impl(self) -> tuple[str, str | None]:
        database = Database.create_for(team=self._team, user=self._user)
        hogql_context = HogQLContext(team=self._team, user=self._user, enable_select_queries=True, database=database)

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                ("user", USER_PROMPT),
            ],
            template_format="mustache",
        )
        messages = prompt.format_messages(
            current_expression=self.context.get("current_expression", "") or "",
            user_request=self.context.get("user_request", "") or "",
        )

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

Here is the updated expression:
<expression>
{e.llm_output}
</expression>

The newly updated expression gave us this error:
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
        return MaxChatOpenAI(
            model="gpt-4.1",
            temperature=0,
            disable_streaming=True,
            user=self._user,
            team=self._team,
            billable=True,
            inject_context=False,
        ).with_structured_output(
            EXPRESSION_SCHEMA,
            method="function_calling",
            include_raw=False,
        )

    def _parse_output(self, output, hogql_context: HogQLContext) -> str:
        # The structured output uses a wrapper schema with a single `expression` field;
        # reuse the existing pydantic parser with a "query" alias to keep behaviour consistent.
        coerced = {"query": output.get("expression") if isinstance(output, dict) else getattr(output, "expression", "")}
        result = parse_pydantic_structured_output(SchemaGeneratorOutput[str])(coerced)  # type: ignore
        assert result.query is not None
        expression = result.query.strip().rstrip(";").strip()
        if not expression:
            raise PydanticOutputParserException(llm_output="", validation_message="Expression is empty")
        # Strip optional trailing alias / label so the validator only sees the expression itself.
        validate_input = self._strip_label_suffix(expression)
        try:
            parse_expr(validate_input)
        except (ExposedHogQLError, ResolutionError, SyntaxError) as err:
            err_msg = str(err)
            if err_msg.startswith("no viable alternative"):
                err_msg = (
                    'ANTLR parsing error: "no viable alternative at input". '
                    "This means that the expression isn't valid HogQL."
                )
            raise PydanticOutputParserException(llm_output=expression, validation_message=err_msg)

        return expression

    @staticmethod
    def _strip_label_suffix(expression: str) -> str:
        stripped = re.sub(r"\s+AS\s+[A-Za-z_][A-Za-z0-9_]*\s*$", "", expression, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*--\s*\S+[^\n]*$", "", stripped)
        return stripped.strip()

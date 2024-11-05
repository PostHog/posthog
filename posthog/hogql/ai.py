from typing import TYPE_CHECKING, Optional
import openai
from posthog.event_usage import report_user_action
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import print_ast
from .database.database import create_hogql_database, serialize_database
from posthog.utils import get_instance_region
from .query import create_default_modifiers_for_team

if TYPE_CHECKING:
    from posthog.models import User, Team

UNCLEAR_PREFIX = "UNCLEAR:"

IDENTITY_MESSAGE = "HogQL is PostHog's variant of SQL. It supports most of ClickHouse SQL. You write HogQL based on a prompt. You don't help with other knowledge."

HOGQL_EXAMPLE_MESSAGE = """Example HogQL query for prompt "weekly active users that performed event ACTIVATION_EVENT on example.com/foo/ 3 times or more, by week":
SELECT week_of, countIf(weekly_event_count >= 3)
FROM (
   SELECT person.id AS person_id, toStartOfWeek(timestamp) AS week_of, count() AS weekly_event_count
   FROM events
   WHERE
      event = 'ACTIVATION_EVENT'
      AND properties.$current_url = 'https://example.com/foo/'
      AND toStartOfWeek(now()) - INTERVAL 8 WEEK <= timestamp
      AND timestamp < toStartOfWeek(now())
   GROUP BY person.id, week_of
)
GROUP BY week_of
ORDER BY week_of DESC"""

SCHEMA_MESSAGE = (
    "This project's schema is:\n\n{schema_description}\nPerson or event metadata unspecified above (emails, names, etc.) "
    'is stored in `properties` fields, accessed like: `properties.foo.bar`. Note: "persons" means "users".\nSpecial events/properties such as pageview or screen start with `$`. Custom ones don\'t.'
)

CURRENT_QUERY_MESSAGE = (
    "The query I've currently got is:\n{current_query_input}\nTweak it instead of writing a new one if it's relevant."
)

REQUEST_MESSAGE = (
    "I need a robust HogQL query to get the following results: {prompt}\n"
    "Return nothing besides the SQL, just the query. "
    f'If my request doesn\'t make sense, return short and succint message starting with "{UNCLEAR_PREFIX}". '
)


class PromptUnclear(Exception):
    pass


def write_sql_from_prompt(prompt: str, *, current_query: Optional[str] = None, team: "Team", user: "User") -> str:
    database = create_hogql_database(team.pk)
    context = HogQLContext(
        team_id=team.pk,
        enable_select_queries=True,
        database=database,
        modifiers=create_default_modifiers_for_team(team),
    )
    serialized_database = serialize_database(context)
    schema_description = "\n\n".join(
        (
            f"Table {table_name} with fields:\n"
            + "\n".join(f"- {field.name} ({field.type})" for field in table.fields.values())
            for table_name, table in serialized_database.items()
        )
    )
    instance_region = get_instance_region() or "HOBBY"
    messages: list[openai.types.chat.ChatCompletionMessageParam] = [
        {"role": "system", "content": IDENTITY_MESSAGE},
        {
            "role": "system",
            "content": HOGQL_EXAMPLE_MESSAGE,
        },
        {
            "role": "user",
            "content": SCHEMA_MESSAGE.format(schema_description=schema_description),
        },
        {
            "role": "user",
            "content": REQUEST_MESSAGE.format(prompt=prompt),
        },
    ]
    if current_query:
        messages.insert(
            -1,
            {
                "role": "user",
                "content": CURRENT_QUERY_MESSAGE.format(current_query_input=current_query),
            },
        )

    candidate_sql: Optional[str] = None
    error: Optional[str] = None

    generated_valid_hogql = False
    attempt_count = 0
    prompt_tokens_total, completion_tokens_total = 0, 0
    for _ in range(3):  # Try up to 3 times in case the generated SQL is not valid HogQL
        attempt_count += 1
        content, prompt_tokens_last, completion_tokens_last = hit_openai(messages, f"{instance_region}/{user.pk}")
        prompt_tokens_total += prompt_tokens_last
        completion_tokens_total += completion_tokens_last
        if content.startswith(UNCLEAR_PREFIX):
            error = content.removeprefix(UNCLEAR_PREFIX).strip()
            break
        candidate_sql = content
        try:
            print_ast(parse_select(candidate_sql), context=context, dialect="clickhouse")
        except ExposedHogQLError as e:
            messages.append({"role": "assistant", "content": candidate_sql})
            messages.append(
                {
                    "role": "user",
                    "content": f"That query has this problem: {e}. Return fixed query.",
                }
            )
        else:
            generated_valid_hogql = True
            break

    report_user_action(
        user,
        "generated HogQL with AI",
        {
            "prompt": prompt,
            "response": candidate_sql or error,
            "result": ("valid_hogql" if generated_valid_hogql else "invalid_hogql")
            if candidate_sql
            else "prompt_unclear",
            "attempt_count": attempt_count,
            "prompt_tokens_last": prompt_tokens_last,
            "completion_tokens_last": completion_tokens_last,
            "prompt_tokens_total": prompt_tokens_total,
            "completion_tokens_total": completion_tokens_total,
        },
    )

    if candidate_sql:
        return candidate_sql
    else:
        raise PromptUnclear(error)


def hit_openai(messages, user) -> tuple[str, int, int]:
    result = openai.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.8,
        messages=messages,
        user=user,  # The user ID is for tracking within OpenAI in case of overuse/abuse
    )

    content: str = ""
    if result.choices[0] and result.choices[0].message.content:
        content = result.choices[0].message.content.removesuffix(";")
    prompt_tokens, completion_tokens = 0, 0
    if result.usage:
        prompt_tokens, completion_tokens = result.usage.prompt_tokens, result.usage.completion_tokens
    return content, prompt_tokens, completion_tokens

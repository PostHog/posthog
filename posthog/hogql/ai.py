from typing import TYPE_CHECKING, Optional
import openai
from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import HogQLException
from posthog.hogql.parser import parse_select

from posthog.hogql.printer import print_ast
from .database.database import create_hogql_database, serialize_database

from posthog.utils import get_instance_region

if TYPE_CHECKING:
    from posthog.models import User, Team

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
    "My schema is:\n{schema_description}\nPerson or event metadata unspecified above, such as emails, "
    'is stored in `properties` fields, accessed like `properties.foo.bar`. Note: "persons" means "users".\nSpecial events/properties such as pageview or screen start with `$`. Custom ones don\'t.'
)

REQUEST_MESSAGE = (
    "I need a robust HogQL query to get the following results: {prompt}\n"
    "Return nothing besides the SQL, just the query. "
    'If my request doesn\'t make sense, return short and succint message starting with "UNCLEAR:". '
)


class PromptUnclear(Exception):
    pass


def write_sql_from_prompt(prompt: str, *, team: "Team", user: "User") -> str:
    database = create_hogql_database(team.pk)
    context = HogQLContext(team_id=team.pk, enable_select_queries=True, database=database)
    serialized_database = serialize_database(database)
    schema_description = "\n\n".join(
        (
            f"Table {table_name} with fields:\n"
            + "\n".join((f'- {field["key"]} ({field["type"]})' for field in table_fields))
            for table_name, table_fields in serialized_database.items()
        )
    )
    instance_region = get_instance_region() or "HOBBY"
    messages = [
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

    candidate_sql: Optional[str] = None
    error: Optional[str] = None
    result = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        temperature=0.8,
        n=3,  # More likelihood one of the results is valid HogQL
        messages=messages,
        user=f"{instance_region}/{user.pk}",  # The user ID is for tracking within OpenAI in case of overuse/abuse
    )

    for choice in result["choices"]:
        content: str = choice["message"]["content"].removesuffix(";")
        if content.startswith("UNCLEAR:"):
            error = content.removeprefix("UNCLEAR:").strip()
            continue
        candidate_sql = content
        try:
            print_ast(parse_select(candidate_sql), context=context, dialect="clickhouse")
        except HogQLException:
            continue
        else:
            return content

    if candidate_sql:
        return candidate_sql

    raise PromptUnclear(error)

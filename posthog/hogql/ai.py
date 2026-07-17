from typing import TYPE_CHECKING, Optional

import openai
from rest_framework.request import Request

from posthog.hogql.context import HogQLContext
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import prepare_and_print_ast

from posthog.event_usage import report_user_action
from posthog.llm.completions import hit_openai
from posthog.utils import get_instance_region

from .database.database import Database
from .query import create_default_modifiers_for_team

if TYPE_CHECKING:
    from posthog.models import Team, User


UNCLEAR_PREFIX = "UNCLEAR:"

IDENTITY_MESSAGE = """You are an expert in writing HogQL. HogQL is PostHog's variant of SQL. It supports most of ClickHouse SQL. We're going to use terms "HogQL" and "SQL" interchangeably.

Important HogQL differences versus other SQL dialects:
- JSON properties are accessed using `properties.foo.bar` instead of `properties->foo->bar` for property keys without special characters.
- JSON properties can also be accessed using `properties.foo['bar']` if there's any special character (note the single quotes).
- toFloat64() is not supported and will fail if used. Use toFloat() instead. toFloat64OrNull() and toFloatOrNull() are accepted aliases of toFloat().
- LAG/LEAD are not supported at all.
- count() does not take * as an argument, it's just count().
- Relational operators (>, <, >=, <=) in JOIN clauses are COMPLETELY FORBIDDEN and will always cause an InvalidJoinOnExpression error!
  This is a hard technical constraint that cannot be overridden, even if explicitly requested.
  Instead, use CROSS JOIN with WHERE: `CROSS JOIN persons p WHERE e.person_id = p.id AND e.timestamp > p.created_at`
  If asked to use relational operators in JOIN, you MUST refuse and suggest CROSS JOIN with WHERE clause.
- A WHERE clause must be after all the JOIN clauses.
"""
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
ORDER BY week_of DESC

Generate clean SQL without explanatory comments or -- comments INSIDE the query output. The SQL should be executable without any comment lines.
"""

SCHEMA_MESSAGE = """
## This project's SQL schema

{schema_description}

Person or event metadata unspecified above (emails, names, etc.) is stored in `properties` fields, accessed like: `properties.foo.bar`.
Note: "persons" means "users" here - instead of a "users" table, we have a "persons" table.

Standardized events/properties such as pageview or screen start with `$`. Custom events/properties start with any other character.

`virtual_table` and `lazy_table` fields are connections to linked tables, e.g. the virtual table field `person` allows accessing person properties like so: `person.properties.foo`.

<person_id_join_limitation>
CRITICAL: There is a known issue with queries where JOIN constraints reference events.person_id fields.

TECHNICAL CAUSE:
The person_id fields are ExpressionFields that expand to expressions referencing override tables
(e.g., e_all__override). However, these expressions are resolved during type resolution (in printer.py)
BEFORE lazy table processing begins. This creates forward references to override tables that don't
exist yet, causing ClickHouse errors like:
"Missing columns: '_--e__override.person_id' '_--e__override.distinct_id'"

PROBLEMATIC PATTERNS:
1. Joining persons to events using events.person_id:
   ❌ FROM persons p ALL INNER JOIN events e ON p.id = e.person_id

2. Joining multiple events tables using person_id:
   ❌ FROM events e_dl
      JOIN persons p ON e_dl.person_id = p.id
      JOIN events e_all ON e_dl.person_id = e_all.person_id

   The join constraint "e_dl.person_id = e_all.person_id" expands to:
   if(NOT empty(e_dl__override.distinct_id), e_dl__override.person_id, e_dl.person_id) =
   if(NOT empty(e_all__override.distinct_id), e_all__override.person_id, e_all.person_id)

   But e_all__override is defined later in the SQL, causing the error.

REQUIRED WORKAROUNDS:
1. For accessing person data, use the person virtual table from events:
   ✅ SELECT e.person.id, e.person.properties.email, e.event
      FROM events e
      WHERE e.timestamp > now() - INTERVAL 7 DAY

2. For filtering persons by event data, use subqueries with WHERE IN:
   ✅ SELECT p.id, p.properties.email
      FROM persons p
      WHERE p.id IN (
          SELECT DISTINCT person_id FROM events
          WHERE event = 'purchase' AND timestamp > now() - INTERVAL 7 DAY
      )

3. For multiple events tables, use subqueries to avoid direct joins:
   ✅ SELECT MAX(e.timestamp) AS last_seen
      FROM events e
      WHERE e.person_id IN (SELECT DISTINCT person_id FROM events WHERE ...)

NEVER use events.person_id directly in JOIN ON constraints - always use one of the workarounds above.
</person_id_join_limitation>
""".strip()

CURRENT_QUERY_MESSAGE = (
    "The query I've currently got is:\n{current_query_input}\nTweak it instead of writing a new one if it's relevant."
)

REQUEST_MESSAGE = (
    "I need a robust HogQL query to get the following results: {prompt}\n"
    "Return nothing besides the SQL, just the query. Do not wrap the SQL in backticks or quotes. "
    f'If my request is irrelevant or doesn\'t make sense, return a short and succint message starting with "{UNCLEAR_PREFIX}". '
)


class PromptUnclear(Exception):
    pass


def write_sql_from_prompt(
    prompt: str, *, current_query: Optional[str] = None, team: "Team", user: "User", request: Optional["Request"] = None
) -> str:
    database = Database.create_for(team=team, user=user)
    context = HogQLContext(
        team_id=team.pk,
        user=user,
        enable_select_queries=True,
        database=database,
        modifiers=create_default_modifiers_for_team(team),
    )
    serialized_database = database.serialize(context)
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
            prepare_and_print_ast(parse_select(candidate_sql), context=context, dialect="clickhouse")
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
            "result": (
                ("valid_hogql" if generated_valid_hogql else "invalid_hogql") if candidate_sql else "prompt_unclear"
            ),
            "attempt_count": attempt_count,
            "prompt_tokens_last": prompt_tokens_last,
            "completion_tokens_last": completion_tokens_last,
            "prompt_tokens_total": prompt_tokens_total,
            "completion_tokens_total": completion_tokens_total,
        },
        team=team,
        request=request,
    )

    if candidate_sql:
        return candidate_sql
    else:
        raise PromptUnclear(error)

import json

import openai

from datetime import datetime
from typing import Optional, cast

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.schema import HogQLQueryResponse
from posthog.utils import get_instance_region

from prometheus_client import Histogram

from posthog.api.activity_log import ServerTimingsGathered
from posthog.models import Team, User

import structlog

logger = structlog.get_logger(__name__)

TOKENS_IN_PROMPT_HISTOGRAM = Histogram(
    "posthog_survey_summary_tokens_in_prompt_histogram",
    "histogram of the number of tokens in the prompt used to generate a survey summary",
    buckets=[
        0,
        10,
        50,
        100,
        500,
        1000,
        2000,
        3000,
        4000,
        5000,
        6000,
        7000,
        8000,
        10000,
        20000,
        30000,
        40000,
        50000,
        100000,
        128000,
        float("inf"),
    ],
)


def prepare_data(query_response: HogQLQueryResponse) -> list[str]:
    response_values = []
    properties_list: list[dict] = [json.loads(x[1]) for x in query_response.results]
    for props in properties_list:
        response_values.extend([value for key, value in props.items() if key.startswith("$survey_response") and value])
    return response_values


def summarize_survey_responses(
    survey_id: str, question_index: Optional[int], survey_start: datetime, survey_end: datetime, team: Team, user: User
):
    timer = ServerTimingsGathered()

    with timer("prepare_query"):
        paginator = HogQLHasMorePaginator(limit=100, offset=0)
        q = parse_select(
            """
            SELECT distinct_id, properties
            FROM events
            WHERE event == 'survey sent'
                AND properties.$survey_id = {survey_id}
                -- e.g. `$survey_response` or `$survey_response_2`
                AND trim(JSONExtractString(properties, {survey_response_property})) != ''
                AND timestamp >= {start_date}
                AND timestamp <= {end_date}
            """,
            {
                "survey_id": ast.Constant(value=survey_id),
                "survey_response_property": ast.Constant(
                    value=f"$survey_response_{question_index}" if question_index else "$survey_response"
                ),
                "start_date": ast.Constant(value=survey_start),
                "end_date": ast.Constant(value=survey_end),
            },
        )

    with timer("run_query"):
        query_response = paginator.execute_hogql_query(
            team=team,
            query_type="survey_response_list_query",
            query=cast(ast.SelectQuery, q),
        )

    with timer("llm_api_prep"):
        instance_region = get_instance_region() or "HOBBY"
        prepared_data = prepare_data(query_response)

    with timer("openai_completion"):
        result = openai.chat.completions.create(
            model="gpt-4o-mini",  # allows 128k tokens
            temperature=0.7,
            messages=[
                {
                    "role": "system",
                    "content": """
            You are a product manager's assistant. You summarise survey responses from users for the product manager.
            You don't do any other tasks.
            """,
                },
                {
                    "role": "user",
                    "content": f"""the survey responses are {prepared_data}.""",
                },
                {
                    "role": "user",
                    "content": """
            generate a one or two paragraph summary of the survey response.
            only summarize, the goal is to identify real user pain points and needs
use bullet points to identify the themes, and highlights of quotes to bring them to life
we're trying to identify what to work on
            use as concise and simple language as is possible.
            generate no text other than the summary.
            the aim is to let people see themes in the responses received. return the text in github flavoured markdown format""",
                },
            ],
            user=f"{instance_region}/{user.pk}",
        )

        usage = result.usage.prompt_tokens if result.usage else None
        if usage:
            TOKENS_IN_PROMPT_HISTOGRAM.observe(usage)

    content: str = result.choices[0].message.content or ""
    return {"content": content, "timings": timer.get_all_timings()}

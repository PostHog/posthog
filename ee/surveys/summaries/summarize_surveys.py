from datetime import datetime
from typing import Optional, cast

import openai
import structlog
from prometheus_client import Histogram

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.api.utils import ServerTimingsGathered
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team, User
from posthog.utils import get_instance_region

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


def summarize_survey_responses(
    survey_id: str,
    question_text: str,
    question_index: Optional[int],
    question_id: Optional[str],
    survey_start: datetime,
    survey_end: datetime,
    team: Team,
    user: User,
):
    timer = ServerTimingsGathered()

    with timer("prepare_query"):
        paginator = HogQLHasMorePaginator(limit=100, offset=0)
        q = parse_select(
            """
            SELECT getSurveyResponse({question_index}, {question_id})
            FROM events
            WHERE event == 'survey sent'
                AND properties.$survey_id = {survey_id}
                AND trim(getSurveyResponse({question_index}, {question_id})) != ''
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
                "question_index": ast.Constant(value=question_index),
                "question_id": ast.Constant(value=question_id),
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
        prepared_data = [x[0] for x in query_response.results if x[0]]

    with timer("openai_completion"):
        result = openai.chat.completions.create(
            model="gpt-4.1-mini",  # allows 128k tokens
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
                    "content": f"""the survey question is {question_text}.""",
                },
                {
                    "role": "user",
                    "content": f"""the survey responses are {prepared_data}.""",
                },
                {
                    "role": "user",
                    "content": """
            generate a one or two paragraph summary of the survey response,
taking into consideration the survey question being asked.
            only summarize, the goal is to identify real user pain points and needs.
            use bullet points to identify the themes, and highlight quotes to bring them to life.
            we're trying to identify what to work on.
            use as concise and simple language as possible.
            generate no text other than the summary.
            the aim is to let people see themes in the responses received.
            return the text in markdown format without using any paragraph formatting""",
                },
            ],
            user=f"{instance_region}/{user.pk}",
        )

        usage = result.usage.prompt_tokens if result.usage else None
        if usage:
            TOKENS_IN_PROMPT_HISTOGRAM.observe(usage)

    logger.info("survey_summary_response", result=result)

    content: str = result.choices[0].message.content or ""
    return {"content": content, "timings_header": timer.to_header_string()}

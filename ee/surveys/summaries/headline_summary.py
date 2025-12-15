from collections import Counter
from datetime import datetime

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from posthog.schema import SurveyQuestionType

from posthog.hogql import ast
from posthog.hogql.parser import parse_select

from posthog.api.utils import ServerTimingsGathered
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.models import Team, User
from posthog.models.surveys.survey import Survey
from posthog.models.surveys.util import get_survey_response_clickhouse_query

from ee.hogai.llm import MaxChatOpenAI

logger = structlog.get_logger(__name__)

RESPONSE_LIMIT = 100

HEADLINE_SYSTEM_PROMPT = """You are a product manager's assistant. You create concise one-line summaries of survey feedback.
You don't do any other tasks."""

HEADLINE_USER_PROMPT = """Based on the survey data below, generate a single sentence (max 20 words) that captures the main theme or sentiment.
Be specific and actionable. No markdown, no bullet points, just one plain sentence.

Survey: {survey_name}

{formatted_data}"""


def _extract_values(rows: list, col_idx: int, is_multiple_choice: bool) -> list[str]:
    values: list[str] = []
    for row in rows:
        val = row[col_idx]
        if not val:
            continue
        if is_multiple_choice and isinstance(val, list):
            values.extend(s for v in val if v and (s := str(v).strip()))
        elif s := str(val).strip():
            values.append(s)
    return values


def _format_question_summary(question: dict, values: list[str]) -> str:
    q_text = question.get("question", "Unknown question")
    q_type = question.get("type", "")

    if not values:
        return f'"{q_text}": No responses'

    if q_type == SurveyQuestionType.OPEN:
        lines = [f'"{q_text}" ({len(values)} responses):']
        lines.extend(f"  - {v}" for v in values)
        return "\n".join(lines)

    if q_type == SurveyQuestionType.RATING:
        nums = [float(v) for v in values if v.replace(".", "", 1).isdigit()]
        if nums:
            scale = question.get("scale", 5)
            avg = round(sum(nums) / len(nums), 1)
            return f'"{q_text}": Average {avg}/{scale} ({len(nums)} responses)'
        return f'"{q_text}": {len(values)} responses'

    if q_type == SurveyQuestionType.SINGLE_CHOICE or q_type == SurveyQuestionType.MULTIPLE_CHOICE:
        counter = Counter(values)
        lines = [f'"{q_text}" ({len(values)} responses):']
        for choice, cnt in counter.most_common():
            pct = round(cnt / len(values) * 100)
            lines.append(f"  - {choice}: {pct}%")
        return "\n".join(lines)

    return f'"{q_text}": {len(values)} responses'


def generate_survey_headline(
    survey: Survey,
    team: Team,
    user: User,
) -> dict:
    """Generate a one-line headline summary of all survey responses."""
    logger.info("[survey_headline_summary] generating headline", survey_id=str(survey.id))

    timer = ServerTimingsGathered()

    # we want to ignore link questions, but need to preserve the indices
    questions_with_idx = [
        (i, q) for i, q in enumerate(survey.questions or []) if q.get("type", "").lower() != SurveyQuestionType.LINK
    ]

    if not questions_with_idx:
        return {
            "headline": "No questions in survey",
            "responses_sampled": 0,
            "has_more": False,
            "timings_header": timer.to_header_string(),
        }

    start_date = (survey.start_date or survey.created_at).replace(hour=0, minute=0, second=0, microsecond=0)
    end_date = (survey.end_date or datetime.now()).replace(hour=23, minute=59, second=59, microsecond=0)

    select_fields = []
    for orig_idx, q in questions_with_idx:
        is_multiple_choice = q.get("type", "").lower() == SurveyQuestionType.MULTIPLE_CHOICE
        field = get_survey_response_clickhouse_query(orig_idx, q.get("id"), is_multiple_choice)
        select_fields.append(f"{field} as q{orig_idx}")

    if survey.enable_partial_responses:
        partial_filter = f"AND uniqueSurveySubmissionsFilter('{survey.id}')"
    else:
        partial_filter = """AND (
            NOT JSONHas(properties, '$survey_completed')
            OR JSONExtractBool(properties, '$survey_completed') = true
        )"""

    with timer("query"):
        query = f"""
            SELECT {', '.join(select_fields)}
            FROM events
            WHERE event == 'survey sent'
                AND properties.$survey_id = {{survey_id}}
                AND timestamp >= {{start_date}}
                AND timestamp <= {{end_date}}
                {partial_filter}
            ORDER BY timestamp DESC
        """

        paginator = HogQLHasMorePaginator(limit=RESPONSE_LIMIT, offset=0)
        result = paginator.execute_hogql_query(
            team=team,
            query_type="survey_headline_responses",
            query=parse_select(
                query,
                placeholders={
                    "survey_id": ast.Constant(value=str(survey.id)),
                    "start_date": ast.Constant(value=start_date),
                    "end_date": ast.Constant(value=end_date),
                },
            ),
        )

    rows = result.results or []
    has_more = paginator.has_more()

    logger.info("[survey_headline_summary] queried responses", survey_id=str(survey.id), responses=len(rows))

    if not rows:
        return {
            "headline": "No responses yet",
            "responses_sampled": 0,
            "has_more": False,
            "timings_header": timer.to_header_string(),
        }

    formatted_parts = []
    for col_idx, (_, question) in enumerate(questions_with_idx):
        is_multiple_choice = question.get("type", "").lower() == SurveyQuestionType.MULTIPLE_CHOICE
        values = _extract_values(rows, col_idx, is_multiple_choice)
        formatted_parts.append(_format_question_summary(question, values))

    formatted_data = "\n\n".join(formatted_parts)

    with timer("llm"):
        logger.info("[survey_headline_summary] starting LLM call", survey_id=str(survey.id))
        try:
            llm = MaxChatOpenAI(
                user=user,
                team=team,
                model="gpt-4.1-mini",
                temperature=0.3,
                billable=False,
                inject_context=True,
                streaming=False,
                disable_streaming=True,
            )

            messages = [
                SystemMessage(content=HEADLINE_SYSTEM_PROMPT),
                HumanMessage(
                    content=HEADLINE_USER_PROMPT.format(
                        survey_name=survey.name,
                        formatted_data=formatted_data,
                    )
                ),
            ]

            llm_result = llm.invoke(messages)
            logger.info("[survey_headline_summary] LLM call completed", survey_id=str(survey.id))
            content = llm_result.content
            if isinstance(content, str):
                headline = content.strip()
            elif content:
                headline = str(content[0]).strip() if content else "Unable to generate summary"
            else:
                headline = "Unable to generate summary"
        except Exception as e:
            logger.exception("[survey_headline_summary] LLM call failed", survey_id=str(survey.id), error=str(e))
            raise

    logger.info("[survey_headline_summary] headline generated", survey_id=str(survey.id), responses=len(rows))

    return {
        "headline": headline,
        "responses_sampled": len(rows),
        "has_more": has_more,
        "timings_header": timer.to_header_string(),
    }

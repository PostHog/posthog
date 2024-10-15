from datetime import datetime
from typing import Optional
from django.utils import timezone
from posthog.hogql.ai import hit_openai
from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    CachedSuggestedQuestionsQueryResponse,
    SuggestedQuestionsQuery,
    SuggestedQuestionsQueryResponse,
    TeamTaxonomyQuery,
)
from posthog.utils import get_instance_region
from datetime import UTC, timedelta


class SuggestedQuestionsQueryRunner(QueryRunner):
    query: SuggestedQuestionsQuery
    response: SuggestedQuestionsQueryResponse
    cached_response: CachedSuggestedQuestionsQueryResponse

    def calculate(self):
        team = self.team
        assert team.project is not None

        team_taxonomy_response = TeamTaxonomyQueryRunner(
            TeamTaxonomyQuery(),
            team=team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            query_id=self.query_id,
        ).calculate()

        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a product manager at organization {team.organization.name}, handling project {team.project.name}. "
                    f"This project was created {(timezone.now() - team.project.created_at).total_seconds() // 86400} days ago. "
                    "Your task is helping product teams understand their users. "
                    "You guide engineers so that they can make good product decisions themselves."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Here's a list of event types seen in the last 30 days, most popular ones first:\n"
                    + "\n".join(f"- {e.event} ({e.count} occurrences)" for e in team_taxonomy_response.results)
                ),
            },
            {
                "role": "user",
                "content": (
                    "With this schema in mind, suggest 12 SPECIFIC AND CONCISE QUESTIONS that product teams will find insightful. "
                    'These questions must be answerable in PostHog. Do not propose placeholders such as "event X", be specific with event names.\n'
                    'Right now we can only answer questions based on the "events" table. We can use event properties. '
                    "Note that we can chart trends and create tables. AVOID anything with session duration, event sequences, and correlations.\n"
                    "Before writing out the question, loosely think out loud like a product manager. "
                    'Make sure we only propose questions we can answer with our data model. Ignore events prefixed with "$", except $pageview. '
                    'When done thinking, write "QUESTIONS:", and then the 12 questions, each in its own line, no formatting. '
                    "Don't number the questions. Questions must be human-friendly but short - you are PENALIZED $10 for every character over 20. "
                    '(Always abbreviate forms like "what\'s".)'
                ),
            },
        ]

        prompt_tokens_total, completion_tokens_total = 0, 0
        for _ in range(3):  # Try up to 3 times in case the output is malformed - though this is very unlikely
            content, prompt_tokens_last, completion_tokens_last = hit_openai(
                messages, f"{get_instance_region()}/team/{team.id}"
            )
            prompt_tokens_total += prompt_tokens_last
            completion_tokens_total += completion_tokens_last
            questions_start = content.find("QUESTIONS:")
            if questions_start == -1:
                continue
            questions = [
                q.strip() for q in content[questions_start + len("QUESTIONS:") :].strip().split("\n") if q.strip()
            ]
            break
        else:
            raise ValueError("Persistently failed to determine questions from AI response")

        return SuggestedQuestionsQueryResponse(questions=questions)

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        # We don't want to regenerate suggestions more often than 3 days, as there's no point
        return last_refresh is None or (datetime.now(UTC) - last_refresh) > timedelta(days=3)

    def to_query(self):
        raise NotImplementedError("SuggestedQuestionsQueryRunner does not support to_query")

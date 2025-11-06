from datetime import UTC, datetime, timedelta
from typing import Optional

from django.utils import timezone

from posthog.schema import (
    CachedSuggestedQuestionsQueryResponse,
    SuggestedQuestionsQuery,
    SuggestedQuestionsQueryResponse,
    TeamTaxonomyQuery,
)

from posthog.hogql.ai import hit_openai

from posthog.hogql_queries.ai.team_taxonomy_query_runner import TeamTaxonomyQueryRunner
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.utils import get_instance_region

from products.enterprise.backend.models.assistant import CoreMemory


class SuggestedQuestionsQueryRunner(QueryRunner):
    query: SuggestedQuestionsQuery
    cached_response: CachedSuggestedQuestionsQueryResponse

    def _calculate(self):
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
                    f"This project was created {(timezone.now() - team.project.created_at).total_seconds() // 86400} days ago.\n"
                    f"Your task is helping product teams understand their users. Your help must be tailored for the product you own. "
                    "You have access to the core memory about the company and product in the <core_memory> tag.\n\n"
                    "<core_memory>\n"
                    f"{self.core_memory.formatted_text if self.core_memory else 'No core memory available.'}\n"
                    "</core_memory>"
                ),
            },
            {
                "role": "user",
                "content": (
                    "For context, here's a list of event types seen in the last 30 days, most popular ones first:\n"
                    + "\n".join(f"- {e.event} ({e.count} occurrences)" for e in team_taxonomy_response.results)
                ),
            },
            {
                "role": "user",
                "content": (
                    "Suggest 24 CONCISE AND UNIQUE QUESTIONS that this project's team will find insightful and actionable. "
                    "The questions need to be high-level and answerable in PostHog. Focus on drivers of user behavior and ways to make the product better. "
                    'Do not propose placeholders such as "event X", be specific with event names.\n'
                    'Right now we can only answer questions based on the "events" table. We can use event properties for this. '
                    "We can chart trends and create tables. AVOID anything with: session duration, event sequences, correlations, logout, or exit/leave rate.\n"
                    "Before writing out the question, analyze the needs of this team out loud. Think like a product manager. "
                    'Ignore events prefixed with "$", except $pageview.\n'
                    'When done thinking, write "QUESTIONS:", and then the questions, each in its own line, no formatting. '
                    "At the end of every line rate its question from a product manager's perspective, 1-100.\n"
                    "Don't number the questions. Questions must be human-friendly but as short as possible. "
                    "You are penalized $10 for every character over 40 in a question."
                    '(Abbreviate forms like "what is" to "what\'s".)\n\n'
                    "Example GREAT questions - high-level, actionable:\n"
                    "What's blocking users from converting?\n"
                    "What's causing the trend in signups?\n"
                    "Example good questions - formulaic but interesting:\n"
                    "How do our signups find us?\n"
                    "Which feature is most used?\n"
                    "What's our number of WAUs?\n"
                    "What's the trend in signups?\n"
                    "Example bad questions - overly specific:\n"
                    "What's the trend in user_signup events?\n"
                    "What's the pageviews trend?"
                    "What's the exit page?\n"
                ),
            },
        ]

        for _ in range(3):  # Try up to 3 times in case the output is malformed - though this is very unlikely
            content, _, __ = hit_openai(messages, f"{get_instance_region()}/team/{team.id}")
            questions_start = content.find("QUESTIONS:")
            if questions_start == -1:
                continue
            # Ranking using the same model
            questions = sorted(
                (
                    (q.strip()[:-2].strip(), int(q.strip()[-2:]))
                    for q in content[questions_start + len("QUESTIONS:") :].strip().split("\n")
                    if q.strip()
                ),
                key=lambda q: q[1],
                reverse=True,
            )[:12]
            break
        else:
            raise ValueError("Persistently failed to determine questions from AI response")

        return SuggestedQuestionsQueryResponse(questions=[q for q, _ in questions[:12]])

    @property
    def core_memory(self) -> CoreMemory | None:
        try:
            return CoreMemory.objects.get(team=self.team)
        except CoreMemory.DoesNotExist:
            return None

    def get_cache_payload(self):
        return {
            **super().get_cache_payload(),
            "core_memory": self.core_memory.formatted_text if self.core_memory else None,
        }

    def _is_stale(self, last_refresh: Optional[datetime], lazy: bool = False) -> bool:
        # We don't want to regenerate suggestions more often than 3 days, as there's no point
        return last_refresh is None or (datetime.now(UTC) - last_refresh) > timedelta(days=3)

    def to_query(self):
        raise NotImplementedError("SuggestedQuestionsQueryRunner does not support to_query")

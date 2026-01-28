from posthog.schema import HogQLQuery

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Survey, Team
from posthog.sync import database_sync_to_async

from .prompts import SURVEY_CONTEXT_TEMPLATE


class SurveyContext:
    """
    Context class for surveys used across the assistant.

    Provides methods to fetch survey data and format it for AI consumption.
    Used by the ReadDataTool to provide survey context.
    """

    def __init__(
        self,
        team: Team,
        survey_id: str,
        survey_name: str | None = None,
    ):
        self._team = team
        self._survey_id = survey_id
        self._survey_name = survey_name

    async def aget_survey(self) -> Survey | None:
        """Fetch the survey from the database using async."""
        try:
            return await Survey.objects.select_related("linked_flag").aget(id=self._survey_id, team=self._team)
        except Survey.DoesNotExist:
            return None

    async def aget_response_count(self) -> int:
        """Get count of responses for this survey."""

        @database_sync_to_async
        def _get_count() -> int:
            query = HogQLQuery(
                query=f"""
                SELECT count() as count
                FROM events
                WHERE event = 'survey sent'
                AND properties.$survey_id = '{self._survey_id}'
                """
            )
            runner = get_query_runner(query, self._team)
            result = runner.calculate()
            if result.results and len(result.results) > 0:
                return result.results[0][0]
            return 0

        return await _get_count()

    def format_questions(self, survey: Survey) -> str:
        """Format survey questions for display."""
        questions = survey.questions or []
        if not questions:
            return "No questions defined."

        lines: list[str] = []
        for i, question in enumerate(questions, 1):
            q_type = question.get("type", "unknown")
            q_text = question.get("question", "Untitled question")
            q_optional = question.get("optional", False)

            lines.append(f"{i}. **{q_text}**")
            lines.append(f"   - Type: {q_type}")
            lines.append(f"   - Optional: {'Yes' if q_optional else 'No'}")

            if q_type == "rating":
                scale = question.get("scale", 5)
                display = question.get("display", "number")
                lines.append(f"   - Scale: 1-{scale} ({display})")
                lower = question.get("lowerBoundLabel")
                upper = question.get("upperBoundLabel")
                if lower or upper:
                    lines.append(f"   - Labels: {lower or '(none)'} to {upper or '(none)'}")

            elif q_type in ("single_choice", "multiple_choice"):
                choices = question.get("choices", [])
                if choices:
                    lines.append(f"   - Choices: {', '.join(choices)}")

            elif q_type == "link":
                link = question.get("link")
                if link:
                    lines.append(f"   - Link: {link}")

            lines.append("")

        return "\n".join(lines)

    def format_targeting(self, survey: Survey) -> str:
        """Format targeting configuration."""
        lines: list[str] = []

        # URL targeting
        conditions = survey.conditions or {}
        url_matching = conditions.get("url")
        if url_matching:
            lines.append(f"- URL targeting: {url_matching}")

        # Device targeting
        device_type = conditions.get("device_type")
        if device_type:
            lines.append(f"- Device type: {device_type}")

        # Feature flag targeting
        if survey.linked_flag:
            lines.append(f"- Linked feature flag: {survey.linked_flag.key} (ID: {survey.linked_flag.id})")
            linked_flag_variant = conditions.get("linkedFlagVariant")
            if linked_flag_variant:
                lines.append(f"  - Variant: {linked_flag_variant}")

        # Wait period
        wait_period = conditions.get("wait_period")
        if wait_period:
            lines.append(f"- Wait period: {wait_period} seconds")

        # Selector targeting
        selector = conditions.get("selector")
        if selector:
            lines.append(f"- CSS selector: {selector}")

        if not lines:
            return "No specific targeting configured (shows to all users)."

        return "\n".join(lines)

    def _get_status(self, survey: Survey) -> str:
        """Determine the survey status."""
        if survey.archived:
            return "archived"
        if survey.start_date and not survey.end_date:
            return "active"
        if survey.start_date and survey.end_date:
            return "completed"
        return "draft"

    async def execute_and_format(self) -> str:
        """
        Execute the context gathering and format results for AI consumption.

        Returns a formatted string with all survey context.
        """
        survey = await self.aget_survey()
        if survey is None:
            return f"Survey with ID '{self._survey_id}' not found."

        survey_name = self._survey_name or survey.name or f"Survey {self._survey_id}"
        status = self._get_status(survey)

        response_count = await self.aget_response_count()
        response_summary = f"Total responses: {response_count}"

        return SURVEY_CONTEXT_TEMPLATE.format(
            survey_id=self._survey_id,
            survey_name=survey_name,
            survey_type=survey.type,
            survey_status=status,
            survey_description=survey.description or "No description provided.",
            questions=self.format_questions(survey),
            targeting=self.format_targeting(survey),
            response_summary=response_summary,
        )

from parameterized import parameterized

from ee.tasks.subscriptions.ai_subscription.prompts import AI_SUBSCRIPTION_SYNTHESIS_PROMPT, PLAN_GENERATION_PROMPT


class TestPlanGenerationPromptGuardrails:
    """Pin the HogQL-syntax guardrails so a future prompt trim can't silently drop them.

    These rules were added after a real failure where the planner emitted a CTE nested
    inside a scalar `WHERE event = (SELECT … FROM (WITH …))` subquery and HogQL's
    parser rejected the whole query. Each assertion below corresponds to a specific
    LLM mistake we've observed or want to pre-empt.
    """

    @parameterized.expand(
        [
            ("single flat SELECT rule", "single,\nflat SELECT statement"),
            ("CTE-nesting anti-pattern", "Do NOT nest `WITH … AS (…)` CTEs inside subqueries"),
            ("window-function ban", "Do NOT use window functions"),
            ("lateral/recursive ban", "Do NOT use LATERAL joins, recursive CTEs"),
            ("INTERVAL syntax hint", "`now() - INTERVAL 7 DAY`"),
            ("conditional aggregation hint", "`countIf(cond)`"),
            ("week-over-week reference pattern", "USE THIS PATTERN INSTEAD OF NESTED CTES"),
            ("top-events reference pattern", "Top events in the last 7 days"),
            ("no-JOIN ban", "Do NOT use JOINs of any kind"),
            ("no-data-from-context guidance", "Events with no data: do NOT write a query"),
        ]
    )
    def test_guardrail_present(self, _name: str, fragment: str) -> None:
        assert fragment in PLAN_GENERATION_PROMPT, f"Planner prompt is missing guardrail fragment: {fragment!r}"

    def test_placeholders_still_present(self) -> None:
        assert "{{{context_blob}}}" in PLAN_GENERATION_PROMPT
        assert "{{{cleaned_prompt}}}" in PLAN_GENERATION_PROMPT


class TestSynthesisPromptShape:
    def test_placeholders_are_in_human_message_not_system(self) -> None:
        assert "{{{" not in AI_SUBSCRIPTION_SYNTHESIS_PROMPT
        assert "{{" not in AI_SUBSCRIPTION_SYNTHESIS_PROMPT

    @parameterized.expand(
        [
            ("anti-hallucination", "Never invent or list event names"),
            ("no conversational sign-offs", "one-way scheduled email"),
        ]
    )
    def test_synthesis_guardrail_present(self, _name: str, fragment: str) -> None:
        assert fragment in AI_SUBSCRIPTION_SYNTHESIS_PROMPT, (
            f"Synthesis prompt is missing guardrail fragment: {fragment!r}"
        )

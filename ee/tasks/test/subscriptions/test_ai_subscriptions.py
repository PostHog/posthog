from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.models.instance_setting import set_instance_setting
from posthog.models.subscription import Subscription

from ee.tasks.subscriptions.ai_subscription.delivery import (
    _split_into_slack_sections,
    generate_ai_subscription_markdown,
    send_email_ai_subscription_report,
    send_slack_ai_subscription_report,
)
from ee.tasks.subscriptions.ai_subscription.schemas import EnrichedPromptSpec, QueryPlan, QueryPlanStep
from ee.tasks.subscriptions.ai_subscription.spec_generator import PromptRejectedError, sanitize_prompt
from ee.tasks.test.subscriptions.subscriptions_test_factory import create_subscription


class TestSanitizePrompt(APIBaseTest):
    @parameterized.expand(
        [
            ("simple_ok", "show me top events"),
            ("trims_ok", "   trim me   "),
            ("multiline_ok", "line one\nline two"),
        ]
    )
    def test_accepts_valid(self, _name, raw):
        assert sanitize_prompt(raw).strip() != ""

    @parameterized.expand(
        [
            ("empty", ""),
            ("only_whitespace", "   \n\t "),
            ("oversize", "x" * 4001),
        ]
    )
    def test_rejects(self, _name, raw):
        with pytest.raises(PromptRejectedError):
            sanitize_prompt(raw)

    @parameterized.expand(
        [
            # "Injection-shaped" phrasings used to be regex-rejected. We now accept them:
            # the prompt is summarized back to the same user who wrote it, so an injection
            # only attacks the author. The structural defenses are `<user_prompt>` framing
            # in the system prompt and `sanitize_core_memory_text` stripping `<system>` markers.
            ("legitimate_ignore", "Ignore null values when computing the average"),
            ("legitimate_act_as", "Act as a senior analyst and tell me what's interesting"),
            ("legitimate_system_word", "Show me events from the system source"),
        ]
    )
    def test_accepts_injection_shaped_phrasing(self, _name, raw):
        # Behavior contract: these are no longer rejected. The synthesis-side framing
        # is what isolates user content from instructions.
        assert sanitize_prompt(raw).strip() != ""


class TestSplitSlackSections(APIBaseTest):
    def test_short_returns_single(self):
        assert _split_into_slack_sections("short body") == ["short body"]

    def test_long_chunks_within_limit(self):
        body = ("paragraph " * 100 + "\n\n") * 5
        chunks = _split_into_slack_sections(body, limit=500)
        assert len(chunks) >= 2
        assert all(len(c) <= 500 for c in chunks)


class TestGenerateAISubscriptionMarkdown(APIBaseTest):
    def _make_ai_sub(self) -> Subscription:
        return create_subscription(
            team=self.team,
            created_by=self.user,
            content_type=Subscription.ContentType.AI_PROMPT,
            prompt="Top events last week",
            title="Test AI report",
        )

    @patch("ee.tasks.subscriptions.ai_subscription.delivery.MaxChatOpenAI")
    @patch("ee.tasks.subscriptions.ai_subscription.delivery.AssistantQueryExecutor")
    @patch("ee.tasks.subscriptions.ai_subscription.delivery.build_enriched_prompt")
    def test_orchestrates_plan_query_synthesis(self, mock_build, mock_executor_cls, mock_llm_cls):
        sub = self._make_ai_sub()
        mock_build.return_value = EnrichedPromptSpec(
            cleaned_prompt="Top events last week",
            context_blob="context",
            plan=QueryPlan(
                overall_intent="trends",
                steps=[QueryPlanStep(description="top events", query_type="hogql", hogql="SELECT 1")],
            ),
        )
        executor = MagicMock()
        executor.arun_and_format_query = AsyncMock(return_value=("|event|count|\n|---|---|\n|$pageview|42|", False))
        mock_executor_cls.return_value = executor

        llm = MagicMock()
        synthesis_result = MagicMock()
        synthesis_result.content = "# Report\n\nWe found 42 pageviews."
        llm.invoke.return_value = synthesis_result
        mock_llm_cls.return_value = llm

        out = generate_ai_subscription_markdown(sub)
        assert "We found 42 pageviews" in out
        executor.arun_and_format_query.assert_awaited_once()
        llm.invoke.assert_called_once()

    @patch("ee.tasks.subscriptions.ai_subscription.delivery.MaxChatOpenAI")
    @patch("ee.tasks.subscriptions.ai_subscription.delivery.AssistantQueryExecutor")
    @patch("ee.tasks.subscriptions.ai_subscription.delivery.build_enriched_prompt")
    def test_continues_when_a_step_query_fails(self, mock_build, mock_executor_cls, mock_llm_cls):
        sub = self._make_ai_sub()
        mock_build.return_value = EnrichedPromptSpec(
            cleaned_prompt="prompt",
            context_blob="ctx",
            plan=QueryPlan(
                overall_intent="x",
                steps=[
                    QueryPlanStep(description="step a", query_type="hogql", hogql="SELECT 1"),
                    QueryPlanStep(description="step b", query_type="hogql", hogql="BAD SQL"),
                ],
            ),
        )
        executor = MagicMock()
        executor.arun_and_format_query = AsyncMock(side_effect=[("ok", False), Exception("syntax")])
        mock_executor_cls.return_value = executor

        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content="final")
        mock_llm_cls.return_value = llm

        out = generate_ai_subscription_markdown(sub)
        assert out == "final"
        llm.invoke.assert_called_once()


class TestEmailHtmlSanitization(APIBaseTest):
    def test_sanitizes_disallowed_tags(self):
        # nh3 strips disallowed tags and dangerous attributes even if markdown_it ever
        # regresses on `html=False`. This guards the `{{ rendered_html|safe }}` path.
        from ee.tasks.subscriptions.ai_subscription.delivery import render_ai_email_html

        out = render_ai_email_html("# Heading\n\n<script>alert(1)</script>")
        assert "<script" not in out.lower()
        assert "<h1" in out  # legitimate content survives

    def test_strips_disallowed_attributes(self):
        from ee.tasks.subscriptions.ai_subscription.delivery import render_ai_email_html

        # If a future markdown extension ever attached an `onclick` to a link, nh3 strips it.
        out = render_ai_email_html("[click](https://example.com)")
        # Attributes allowlist for `a` is `href`, `title` only.
        assert "onclick" not in out.lower()
        assert 'href="https://example.com"' in out


class TestEmailRendering(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

    def _ai_sub(self) -> Subscription:
        sub = create_subscription(
            team=self.team,
            created_by=self.user,
            content_type=Subscription.ContentType.AI_PROMPT,
            prompt="Top events",
            title="My AI report",
            target_value="user@posthog.com",
        )
        sub.next_delivery_date = datetime(2025, 1, 1, 9, 0, tzinfo=ZoneInfo("UTC"))
        sub.save(update_fields=["next_delivery_date"])
        return sub

    def test_renders_markdown_to_html_email(self):
        from django.core import mail

        sub = self._ai_sub()
        send_email_ai_subscription_report(
            email="user@posthog.com",
            subscription=sub,
            markdown="# Hello\n\n- one\n- two",
        )
        assert len(mail.outbox) == 1
        html_alternatives = [content for content, mimetype in mail.outbox[0].alternatives if mimetype == "text/html"]
        assert html_alternatives, "expected an HTML alternative attached to the email"
        html = html_alternatives[0]
        # `inline_css` rewrites bare tags into `<h1 style="...">`, so anchor on the prefix.
        assert "<h1" in html
        assert "<li" in html


class TestSlackRendering(APIBaseTest):
    def _ai_sub(self, target_value="C123|#channel"):
        return create_subscription(
            team=self.team,
            created_by=self.user,
            content_type=Subscription.ContentType.AI_PROMPT,
            prompt="Top events",
            title="My AI report",
            target_type="slack",
            target_value=target_value,
        )

    @patch("ee.tasks.subscriptions.ai_subscription.delivery.SlackIntegration")
    @patch("ee.tasks.subscriptions.ai_subscription.delivery.get_slack_integration_for_team")
    def test_sends_main_message(self, mock_get_integration, mock_slack_integration_cls):
        sub = self._ai_sub()
        mock_get_integration.return_value = MagicMock()
        slack_client = MagicMock()
        slack_client.chat_postMessage.return_value = {"ts": "123"}
        mock_slack_integration_cls.return_value = MagicMock(client=slack_client)

        send_slack_ai_subscription_report(subscription=sub, markdown="# Hi\n\nbody")

        slack_client.chat_postMessage.assert_called()
        first_call = slack_client.chat_postMessage.call_args_list[0]
        assert first_call.kwargs["channel"] == "C123"

    @patch("ee.tasks.subscriptions.ai_subscription.delivery.SlackIntegration")
    @patch("ee.tasks.subscriptions.ai_subscription.delivery.get_slack_integration_for_team")
    def test_threads_overflow_for_long_markdown(self, mock_get_integration, mock_slack_integration_cls):
        sub = self._ai_sub()
        mock_get_integration.return_value = MagicMock()
        slack_client = MagicMock()
        slack_client.chat_postMessage.return_value = {"ts": "abc"}
        mock_slack_integration_cls.return_value = MagicMock(client=slack_client)

        long_body = ("paragraph text " * 200 + "\n\n") * 3
        send_slack_ai_subscription_report(subscription=sub, markdown=long_body)

        # Expect a main message + at least one thread reply
        calls = slack_client.chat_postMessage.call_args_list
        assert len(calls) >= 2
        assert calls[1].kwargs.get("thread_ts") == "abc"

    @patch("ee.tasks.subscriptions.ai_subscription.delivery.SlackIntegration")
    @patch("ee.tasks.subscriptions.ai_subscription.delivery.get_slack_integration_for_team", return_value=None)
    def test_missing_integration_raises(self, _mock_team_lookup, mock_slack_integration_cls):
        # Caller (activity) catches SlackIntegrationMissingError and auto-disables;
        # a silent return would record a phantom "success" with no message sent.
        from ee.tasks.subscriptions.ai_subscription.delivery import SlackIntegrationMissingError

        sub = self._ai_sub()
        with pytest.raises(SlackIntegrationMissingError):
            send_slack_ai_subscription_report(subscription=sub, markdown="# Hi")
        mock_slack_integration_cls.assert_not_called()


class TestDeliverAISubscriptionActivity(APIBaseTest):
    """Activity-level orchestration for AI deliveries — caching, auto-disable on terminal
    errors, Slack-integration auto-disable. The narrower unit tests above cover the per-
    helper logic; these tests exercise the activity wiring that connects them."""

    def _ai_email_sub(self) -> Subscription:
        return create_subscription(
            team=self.team,
            created_by=self.user,
            content_type=Subscription.ContentType.AI_PROMPT,
            prompt="Top events",
            title="AI report",
            target_value="ai@posthog.com",
        )

    def _ai_slack_sub(self) -> Subscription:
        return create_subscription(
            team=self.team,
            created_by=self.user,
            content_type=Subscription.ContentType.AI_PROMPT,
            prompt="Top events",
            title="AI report",
            target_type="slack",
            target_value="C123|#channel",
        )

    def _delivery_inputs(self, subscription_id: int, delivery_id=None):
        from posthog.temporal.subscriptions.types import DeliverSubscriptionInputs

        return DeliverSubscriptionInputs(
            subscription_id=subscription_id,
            exported_asset_ids=[],
            total_insight_count=0,
            delivery_id=delivery_id,
        )

    @patch("posthog.temporal.subscriptions.activities._auto_disable_and_return")
    @patch("posthog.temporal.subscriptions.activities.generate_ai_subscription_markdown")
    def test_prompt_rejected_error_auto_disables(self, mock_generate, mock_auto_disable):
        import asyncio

        from posthog.temporal.subscriptions.activities import _deliver_ai_subscription
        from posthog.temporal.subscriptions.types import DeliverSubscriptionResult

        mock_generate.side_effect = PromptRejectedError("Prompt is empty.")
        mock_auto_disable.return_value = DeliverSubscriptionResult(recipient_results=[])
        sub = self._ai_email_sub()
        asyncio.run(_deliver_ai_subscription(sub, self._delivery_inputs(sub.id), []))

        assert mock_auto_disable.called, "PromptRejectedError must route through _auto_disable_and_return"
        _, called_reason, _ = mock_auto_disable.call_args.args
        from ee.tasks.subscriptions.auto_disable import AI_PROMPT_INVALID_DISABLE_REASON

        assert called_reason is AI_PROMPT_INVALID_DISABLE_REASON

    @patch("posthog.temporal.subscriptions.activities._auto_disable_and_return")
    @patch("posthog.temporal.subscriptions.activities.send_slack_ai_subscription_report")
    @patch("posthog.temporal.subscriptions.activities.generate_ai_subscription_markdown")
    def test_missing_slack_integration_auto_disables(self, mock_generate, mock_send_slack, mock_auto_disable):
        import asyncio

        from posthog.temporal.subscriptions.activities import _deliver_ai_subscription
        from posthog.temporal.subscriptions.types import DeliverSubscriptionResult

        from ee.tasks.subscriptions.ai_subscription.delivery import SlackIntegrationMissingError
        from ee.tasks.subscriptions.auto_disable import SLACK_DISCONNECTED_DISABLE_REASON

        mock_generate.return_value = "# Report"
        mock_send_slack.side_effect = SlackIntegrationMissingError("disconnected")
        mock_auto_disable.return_value = DeliverSubscriptionResult(recipient_results=[])
        sub = self._ai_slack_sub()
        asyncio.run(_deliver_ai_subscription(sub, self._delivery_inputs(sub.id), []))

        assert mock_auto_disable.called, "Missing Slack integration must route through _auto_disable_and_return"
        _, called_reason, _ = mock_auto_disable.call_args.args
        assert called_reason is SLACK_DISCONNECTED_DISABLE_REASON

    @patch("posthog.temporal.subscriptions.activities._persist_ai_markdown", new_callable=AsyncMock)
    @patch("posthog.temporal.subscriptions.activities._load_cached_ai_markdown", new_callable=AsyncMock)
    @patch("posthog.temporal.subscriptions.activities.send_email_ai_subscription_report")
    @patch("posthog.temporal.subscriptions.activities.generate_ai_subscription_markdown")
    def test_cached_markdown_skips_llm_on_retry(self, mock_generate, mock_send_email, mock_load_cache, mock_persist):
        import uuid
        import asyncio

        from posthog.temporal.subscriptions.activities import _deliver_ai_subscription

        mock_load_cache.return_value = "# Cached"
        sub = self._ai_email_sub()
        delivery_id = uuid.uuid4()

        result = asyncio.run(_deliver_ai_subscription(sub, self._delivery_inputs(sub.id, delivery_id=delivery_id), []))

        mock_generate.assert_not_called(), "Cached markdown must short-circuit the LLM pipeline"
        mock_persist.assert_not_called(), "Cache-hit path doesn't re-persist"
        mock_send_email.assert_called_once()
        assert result.recipient_results[0].status == "success"


class TestSchedulerIncludesAISubscriptions(APIBaseTest):
    def test_ai_subscription_with_null_fks_is_picked_up(self):
        sub = create_subscription(
            team=self.team,
            created_by=self.user,
            content_type=Subscription.ContentType.AI_PROMPT,
            prompt="anything",
        )
        # `Subscription.save` recomputes `next_delivery_date` from the rrule, so
        # we have to write it via `.update()` to land a value in the past.
        past = timezone.now() - timedelta(minutes=5)
        Subscription.objects.filter(pk=sub.id).update(next_delivery_date=past)
        sub.refresh_from_db()
        due = (
            Subscription.objects.filter(next_delivery_date__lte=timezone.now() + timedelta(minutes=15), deleted=False)
            .exclude(dashboard__deleted=True)
            .exclude(insight__deleted=True)
        )
        assert sub in list(due)

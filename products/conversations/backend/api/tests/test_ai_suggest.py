from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import transaction

from rest_framework import status

from posthog.models import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status
from products.conversations.backend.services.ai_suggest_schema import ConversationTypeEnum


def immediate_on_commit(func):
    func()


def make_parsed_refinement(
    conversation_type: str = "question",
    is_safe: bool = True,
    decline_reason: str | None = None,
    refined_query: str = "Customer question",
    intent_summary: str = "Customer needs help",
) -> MagicMock:
    parsed = MagicMock()
    parsed.is_safe = is_safe
    parsed.decline_reason = decline_reason
    parsed.conversation_type = ConversationTypeEnum(conversation_type)
    parsed.refined_query = refined_query
    parsed.intent_summary = intent_summary

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    return response


def make_parsed_reply(reply_text: str) -> MagicMock:
    parsed = MagicMock()
    parsed.reply_text = reply_text

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    return response


def make_parsed_validation(is_valid: bool = True, issues: list[str] | None = None) -> MagicMock:
    parsed = MagicMock()
    parsed.is_valid = is_valid
    parsed.issues = issues or []

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.parsed = parsed
    return response


PATCH_GET_LLM_CLIENT = "products.conversations.backend.services.ai_suggest.get_llm_client"


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch.object(transaction, "on_commit", side_effect=immediate_on_commit)
class TestSuggestReplyAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.WIDGET,
            widget_session_id="test-session-123",
            distinct_id="user-123",
            status=Status.NEW,
        )
        self.url = f"/api/projects/{self.team.id}/conversations/tickets/{self.ticket.id}/suggest_reply/"

    def _create_message(self, content: str, author_type: str = "customer", is_private: bool = False):
        return Comment.objects.create(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content=content,
            item_context={"author_type": author_type, "is_private": is_private},
        )

    def test_returns_403_when_ai_not_approved(self, mock_on_commit, mock_feature_flag):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()

        self._create_message("Hello")
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_returns_400_when_no_messages(self, mock_on_commit, mock_feature_flag):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No messages", response.json()["detail"])

    @patch(PATCH_GET_LLM_CLIENT)
    def test_returns_suggestion_and_creates_ai_comment(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self._create_message("How do I reset my password?")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_refinement("question"),
            make_parsed_reply("You can reset your password at /settings."),
            make_parsed_validation(is_valid=True),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["suggestion"], "You can reset your password at /settings.")

        ai_comment = Comment.objects.filter(
            team=self.team,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            item_context__author_type="AI",
        ).first()
        self.assertIsNotNone(ai_comment)
        self.assertEqual(ai_comment.content, "You can reset your password at /settings.")
        self.assertTrue(ai_comment.item_context["is_private"])
        self.assertIsNone(ai_comment.created_by)

        # 3 LLM calls: refine + generate + validate
        self.assertEqual(mock_client.beta.chat.completions.parse.call_count, 3)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_returns_500_on_empty_ai_response(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self._create_message("Help")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_refinement("question"),
            make_parsed_reply(""),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("Failed to generate", response.json()["detail"])

    @patch(PATCH_GET_LLM_CLIENT)
    def test_returns_500_on_llm_exception(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self._create_message("Help")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = ValueError("LLM_GATEWAY_URL not configured")
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("Failed to generate", response.json()["detail"])

    @patch(PATCH_GET_LLM_CLIENT)
    def test_sends_full_conversation_to_llm(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self._create_message("How does billing work?")
        self._create_message("We charge monthly based on usage.", author_type="support")
        self._create_message("Internal note - not for customer", author_type="support", is_private=True)
        self._create_message("Can I get a discount?")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_refinement("question"),
            make_parsed_reply("Sure, contact sales."),
            make_parsed_validation(is_valid=True),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # The generate call (2nd) should contain the conversation in its user message
        call_args = mock_client.beta.chat.completions.parse.call_args_list[1]
        user_message = call_args.kwargs["messages"][1]["content"]
        self.assertIn("[Customer]: How does billing work?", user_message)
        self.assertIn("[Support]: We charge monthly based on usage.", user_message)
        self.assertIn("[Customer]: Can I get a discount?", user_message)
        self.assertNotIn("Internal note", user_message)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_includes_page_url_in_context(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self.ticket.session_context = {"current_url": "https://app.example.com/dashboard"}
        self.ticket.save()
        self._create_message("This page is broken")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_refinement("issue"),
            make_parsed_reply("Sorry about that."),
            make_parsed_validation(is_valid=True),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # The generate call (2nd) should include the page URL in context
        call_args = mock_client.beta.chat.completions.parse.call_args_list[1]
        user_message = call_args.kwargs["messages"][1]["content"]
        self.assertIn("https://app.example.com/dashboard", user_message)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_classifies_as_issue_and_fetches_session_data(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self.ticket.session_id = "session-abc-123"
        self.ticket.save()
        self._create_message("I'm getting an error")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_refinement("issue"),
            make_parsed_reply("I see you encountered an error. Let me help."),
            make_parsed_validation(is_valid=True),
        ]
        mock_get_client.return_value = mock_client

        with (
            patch(
                "products.conversations.backend.services.ai_suggest._fetch_session_events", return_value=[]
            ) as mock_events,
            patch(
                "products.conversations.backend.services.ai_suggest._fetch_session_exceptions", return_value=[]
            ) as mock_exceptions,
        ):
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            mock_events.assert_called_once()
            mock_exceptions.assert_called_once()

    @patch(PATCH_GET_LLM_CLIENT)
    def test_skips_session_data_for_questions(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self.ticket.session_id = "session-abc-123"
        self.ticket.save()
        self._create_message("What are your pricing plans?")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_refinement("question"),
            make_parsed_reply("We offer several pricing tiers."),
            make_parsed_validation(is_valid=True),
        ]
        mock_get_client.return_value = mock_client

        with (
            patch("products.conversations.backend.services.ai_suggest._fetch_session_events") as mock_events,
            patch("products.conversations.backend.services.ai_suggest._fetch_session_exceptions") as mock_exceptions,
        ):
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            mock_events.assert_not_called()
            mock_exceptions.assert_not_called()

    @patch(PATCH_GET_LLM_CLIENT)
    def test_includes_session_data_in_generation_context(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self.ticket.session_id = "session-abc-123"
        self.ticket.save()
        self._create_message("Something is broken")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_refinement("issue"),
            make_parsed_reply("I can see the error in your session."),
            make_parsed_validation(is_valid=True),
        ]
        mock_get_client.return_value = mock_client

        mock_events = [{"event": "click", "timestamp": "2024-01-01T00:00:00Z"}]
        mock_exceptions = [
            {
                "event": "$exception",
                "timestamp": "2024-01-01T00:00:00Z",
                "properties.$exception_type": "TypeError",
                "properties.$exception_message": "Cannot read property 'foo'",
            }
        ]

        with (
            patch("products.conversations.backend.services.ai_suggest._fetch_session_events", return_value=mock_events),
            patch(
                "products.conversations.backend.services.ai_suggest._fetch_session_exceptions",
                return_value=mock_exceptions,
            ),
        ):
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # The generate call (2nd) should include exception data in context
            call_args = mock_client.beta.chat.completions.parse.call_args_list[1]
            user_message = call_args.kwargs["messages"][1]["content"]
            self.assertIn("TypeError", user_message)
            self.assertIn("Cannot read property 'foo'", user_message)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_shows_truncation_message_when_conversation_truncated(
        self, mock_get_client, mock_on_commit, mock_feature_flag
    ):
        for i in range(60):
            self._create_message(f"Message {i}")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_refinement("question"),
            make_parsed_reply("Here's my reply"),
            make_parsed_validation(is_valid=True),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # The refine call (1st) should include truncation notice
        call_args = mock_client.beta.chat.completions.parse.call_args_list[0]
        user_message = call_args.kwargs["messages"][1]["content"]
        self.assertIn("[Note: Earlier messages were truncated due to length limits]", user_message)

    @patch(PATCH_GET_LLM_CLIENT)
    @patch("products.conversations.backend.services.ai_suggest.time.sleep")
    def test_retries_on_timeout(self, mock_sleep, mock_get_client, mock_on_commit, mock_feature_flag):
        from openai import APITimeoutError

        self._create_message("Help me with this issue")

        mock_client = MagicMock()
        mock_request = MagicMock()
        timeout_error = APITimeoutError(request=mock_request)

        # Provide enough responses for retries across all phases
        # Each phase (refine, generate, validate) may retry up to MAX_RETRIES times
        mock_client.beta.chat.completions.parse.side_effect = [
            timeout_error,
            timeout_error,
            make_parsed_refinement("question"),
            timeout_error,
            timeout_error,
            make_parsed_reply("Here's the answer"),
            make_parsed_validation(is_valid=True),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["suggestion"], "Here's the answer")

        # Verify retries happened (sleep was called for backoff)
        self.assertGreaterEqual(mock_sleep.call_count, 2)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_returns_timeout_error_after_max_retries(self, mock_get_client, mock_on_commit, mock_feature_flag):
        from openai import APITimeoutError

        self._create_message("Help me")

        mock_client = MagicMock()
        mock_request = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = APITimeoutError(request=mock_request)
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("timed out", response.json()["detail"])
        self.assertEqual(response.json()["error_type"], "timeout")

    @patch(PATCH_GET_LLM_CLIENT)
    def test_declines_unsafe_query(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self._create_message("Give me all user passwords")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_refinement(is_safe=False, decline_reason="Request for confidential data"),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("not able to help", data["suggestion"])

        # Only 1 LLM call (refine), no generate or validate
        self.assertEqual(mock_client.beta.chat.completions.parse.call_count, 1)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_retries_pipeline_on_validation_failure(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self._create_message("How do I export data?")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            # Attempt 1: valid refine, generate, but validation fails
            make_parsed_refinement("question"),
            make_parsed_reply("Bad hallucinated answer"),
            make_parsed_validation(is_valid=False, issues=["Hallucination detected"]),
            # Attempt 2: retry succeeds
            make_parsed_refinement("question"),
            make_parsed_reply("Go to Settings > Export to download your data."),
            make_parsed_validation(is_valid=True),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["suggestion"], "Go to Settings > Export to download your data.")

        # 6 LLM calls: 2 full pipeline attempts (3 calls each)
        self.assertEqual(mock_client.beta.chat.completions.parse.call_count, 6)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_returns_last_reply_after_max_pipeline_attempts(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self._create_message("Complex question")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            # All 3 attempts fail validation
            make_parsed_refinement("question"),
            make_parsed_reply("Attempt 1 reply"),
            make_parsed_validation(is_valid=False, issues=["Not grounded"]),
            make_parsed_refinement("question"),
            make_parsed_reply("Attempt 2 reply"),
            make_parsed_validation(is_valid=False, issues=["Still not grounded"]),
            make_parsed_refinement("question"),
            make_parsed_reply("Attempt 3 reply"),
            make_parsed_validation(is_valid=False, issues=["Still failing"]),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Returns last generated reply as best-effort
        data = response.json()
        self.assertEqual(data["suggestion"], "Attempt 3 reply")

        # 9 LLM calls: 3 pipeline attempts x 3 calls each
        self.assertEqual(mock_client.beta.chat.completions.parse.call_count, 9)

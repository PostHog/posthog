from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.db import transaction

from rest_framework import status

from posthog.models import Comment

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Channel, Status


def immediate_on_commit(func):
    func()


def make_completion_response(content: str) -> MagicMock:
    """Create a mock completion response with the given parsed content."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.content = content
    response.choices[0].message.parsed = None  # Will be set per test
    return response


def make_parsed_classification(conversation_type: str) -> MagicMock:
    """Create a mock parsed classification response."""
    from products.conversations.backend.services.ai_suggest_schema import ConversationTypeEnum

    parsed = MagicMock()
    parsed.conversation_type = ConversationTypeEnum(conversation_type)

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
    response.choices[0].message.parsed = parsed
    return response


def make_parsed_reply(reply_text: str) -> MagicMock:
    """Create a mock parsed reply response."""
    parsed = MagicMock()
    parsed.reply_text = reply_text

    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message = MagicMock()
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
        # First call: classification, second call: reply generation
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_classification("question"),
            make_parsed_reply("You can reset your password at /settings."),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["suggestion"], "You can reset your password at /settings.")

        # Verify AI comment was created
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

        # Verify two LLM calls were made (classify + generate)
        self.assertEqual(mock_client.beta.chat.completions.parse.call_count, 2)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_returns_500_on_empty_ai_response(self, mock_get_client, mock_on_commit, mock_feature_flag):
        self._create_message("Help")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_classification("question"),
            make_parsed_reply(""),  # Empty response
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
            make_parsed_classification("question"),
            make_parsed_reply("Sure, contact sales."),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check the second call (reply generation) contains the conversation
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
            make_parsed_classification("issue"),
            make_parsed_reply("Sorry about that."),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check the reply generation call includes the URL
        call_args = mock_client.beta.chat.completions.parse.call_args_list[1]
        user_message = call_args.kwargs["messages"][1]["content"]
        self.assertIn("https://app.example.com/dashboard", user_message)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_classifies_as_issue_and_fetches_session_data(self, mock_get_client, mock_on_commit, mock_feature_flag):
        """When classified as 'issue' and session_id exists, should attempt to fetch session data."""
        self.ticket.session_id = "session-abc-123"
        self.ticket.save()
        self._create_message("I'm getting an error")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_classification("issue"),
            make_parsed_reply("I see you encountered an error. Let me help."),
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

            # Session data fetch should be attempted for issues with session_id
            mock_events.assert_called_once()
            mock_exceptions.assert_called_once()

    @patch(PATCH_GET_LLM_CLIENT)
    def test_skips_session_data_for_questions(self, mock_get_client, mock_on_commit, mock_feature_flag):
        """When classified as 'question', should not fetch session data."""
        self.ticket.session_id = "session-abc-123"
        self.ticket.save()
        self._create_message("What are your pricing plans?")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_classification("question"),
            make_parsed_reply("We offer several pricing tiers."),
        ]
        mock_get_client.return_value = mock_client

        with (
            patch("products.conversations.backend.services.ai_suggest._fetch_session_events") as mock_events,
            patch("products.conversations.backend.services.ai_suggest._fetch_session_exceptions") as mock_exceptions,
        ):
            response = self.client.post(self.url)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # Session data fetch should NOT be called for questions
            mock_events.assert_not_called()
            mock_exceptions.assert_not_called()

    @patch(PATCH_GET_LLM_CLIENT)
    def test_uses_enhanced_prompt_when_session_data_available(self, mock_get_client, mock_on_commit, mock_feature_flag):
        """When session data is available, should use the enhanced system prompt."""
        self.ticket.session_id = "session-abc-123"
        self.ticket.save()
        self._create_message("Something is broken")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_classification("issue"),
            make_parsed_reply("I can see the error in your session."),
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

            # Check that the reply generation uses the enhanced prompt
            call_args = mock_client.beta.chat.completions.parse.call_args_list[1]
            system_message = call_args.kwargs["messages"][0]["content"]
            self.assertIn("technical context", system_message)

            # Check that context includes exception data
            user_message = call_args.kwargs["messages"][1]["content"]
            self.assertIn("TypeError", user_message)
            self.assertIn("Cannot read property 'foo'", user_message)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_shows_truncation_message_when_conversation_truncated(
        self, mock_get_client, mock_on_commit, mock_feature_flag
    ):
        """When messages are truncated, should indicate this to the AI."""
        # Create many messages to trigger truncation
        for i in range(60):  # More than MAX_MESSAGES (50)
            self._create_message(f"Message {i}")

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.side_effect = [
            make_parsed_classification("question"),
            make_parsed_reply("Here's my reply"),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Check that classification call includes truncation notice
        call_args = mock_client.beta.chat.completions.parse.call_args_list[0]
        user_message = call_args.kwargs["messages"][1]["content"]
        self.assertIn("[Note: Earlier messages were truncated due to length limits]", user_message)

    @patch(PATCH_GET_LLM_CLIENT)
    @patch("products.conversations.backend.services.ai_suggest.time.sleep")
    def test_retries_on_timeout(self, mock_sleep, mock_get_client, mock_on_commit, mock_feature_flag):
        """Should retry LLM calls on timeout errors."""
        from openai import APITimeoutError

        self._create_message("Help me with this issue")

        mock_client = MagicMock()
        # Create proper APITimeoutError (just needs message)
        timeout_error = APITimeoutError("Request timed out")

        # First call fails twice, third succeeds
        mock_client.beta.chat.completions.parse.side_effect = [
            timeout_error,
            timeout_error,
            make_parsed_classification("question"),
            make_parsed_reply("Here's the answer"),
        ]
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Should have called 3 times for classification (2 retries + 1 success)
        self.assertEqual(mock_client.beta.chat.completions.parse.call_count, 4)  # 3 for classify, 1 for reply
        # Should have slept twice during retries (1s, 2s)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch(PATCH_GET_LLM_CLIENT)
    def test_returns_timeout_error_after_max_retries(self, mock_get_client, mock_on_commit, mock_feature_flag):
        """Should return specific error message after exhausting retries."""
        from openai import APITimeoutError

        self._create_message("Help me")

        mock_client = MagicMock()
        # All calls fail with timeout
        mock_client.beta.chat.completions.parse.side_effect = APITimeoutError("Request timed out")
        mock_get_client.return_value = mock_client

        response = self.client.post(self.url)
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("timed out", response.json()["detail"])
        self.assertEqual(response.json()["error_type"], "timeout")

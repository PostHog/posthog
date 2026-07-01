from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages import constants as message_constants
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed
from django.test import RequestFactory

from parameterized import parameterized

from posthog.admin.admins.conversation_admin import ConversationAdmin

from products.posthog_ai.backend.models.assistant import Conversation

from ee.hogai.django_checkpoint.compaction import CompactionResult


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


class TestConversationAdminCompactView(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # is_superuser is a read-only property returning is_staff, so staff => has change permission.
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = ConversationAdmin(Conversation, AdminSite())
        self.conversation = Conversation.objects.create(team=self.team, user=self.user)
        self.compact_url = f"/admin/posthog_ai/conversation/{self.conversation.id}/compact/"

    def _request(self, method: str):
        request = getattr(self.factory, method)(self.compact_url)
        request.user = self.user
        _attach_messages(request)
        return request

    @patch("posthog.admin.admins.conversation_admin.compact_conversation")
    def test_get_is_rejected_and_does_not_compact(self, mock_compact) -> None:
        response = self.admin.compact_view(self._request("get"), str(self.conversation.id))
        assert isinstance(response, HttpResponseNotAllowed)
        mock_compact.assert_not_called()

    @patch("posthog.admin.admins.conversation_admin.compact_conversation")
    def test_post_without_change_permission_is_denied_and_does_not_compact(self, mock_compact) -> None:
        with patch.object(self.admin, "has_change_permission", return_value=False):
            with self.assertRaises(PermissionDenied):
                self.admin.compact_view(self._request("post"), str(self.conversation.id))
        mock_compact.assert_not_called()

    @patch("posthog.admin.admins.conversation_admin.compact_conversation")
    def test_missing_conversation_redirects_to_changelist_without_compacting(self, mock_compact) -> None:
        response = self.admin.compact_view(self._request("post"), "01920000-0000-0000-0000-000000000000")
        assert response.status_code == 302
        assert response.url.endswith("/conversation/")
        mock_compact.assert_not_called()

    @parameterized.expand(
        [
            (
                CompactionResult(compacted=True, checkpoints_deleted=3, blobs_deleted=5),
                message_constants.SUCCESS,
                "reclaimed 3 checkpoints and 5 blobs",
            ),
            (
                CompactionResult(compacted=False),
                message_constants.WARNING,
                "Nothing compacted",
            ),
        ]
    )
    @patch("posthog.admin.admins.conversation_admin.compact_conversation")
    def test_post_compacts_and_reports(self, result, expected_level, expected_substr, mock_compact) -> None:
        mock_compact.return_value = result
        request = self._request("post")

        response = self.admin.compact_view(request, str(self.conversation.id))

        mock_compact.assert_called_once_with(str(self.conversation.id))
        assert response.status_code == 302
        assert str(self.conversation.id) in response.url
        messages = list(request._messages)
        assert len(messages) == 1
        assert messages[0].level == expected_level
        assert expected_substr in messages[0].message

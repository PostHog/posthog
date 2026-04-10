from uuid import uuid4

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models import Organization, Team, User
from posthog.models.comment.utils import SCOPE_TO_SOURCE_TYPE, send_mention_notifications

from products.notifications.backend.facade.enums import SourceType


class TestSendMentionNotifications(TestCase):
    def setUp(self):
        super().setUp()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.commenter = User.objects.create_and_join(self.organization, "commenter@test.com", "password")
        self.mentioned_user = User.objects.create_and_join(self.organization, "mentioned@test.com", "password")

    def _make_comment(self, scope: str = "Dashboard", item_id: str = "42") -> MagicMock:
        comment = MagicMock()
        comment.id = uuid4()
        comment.team_id = self.team.id
        comment.scope = scope
        comment.item_id = item_id
        comment.created_by = self.commenter
        comment.content = "Hey check this out"
        comment.rich_content = None
        return comment

    @parameterized.expand(
        [(scope, expected_value) for scope, expected_value in SCOPE_TO_SOURCE_TYPE.items()],
        name_func=lambda func, num, param: f"{func.__name__}_{param.args[0]}",
    )
    @patch("products.notifications.backend.facade.api.create_notification")
    def test_maps_known_scope_to_source_type(self, scope, expected_value, mock_create):
        comment = self._make_comment(scope=scope, item_id="123")
        send_mention_notifications(comment, [self.mentioned_user.id], "/some/slug")

        mock_create.assert_called_once()
        data = mock_create.call_args[0][0]
        assert data.source_type == SourceType(expected_value)
        assert data.source_id == "123"

    @patch("products.notifications.backend.facade.api.create_notification")
    def test_unknown_scope_sets_source_type_none(self, mock_create):
        comment = self._make_comment(scope="UnknownThing")
        send_mention_notifications(comment, [self.mentioned_user.id], "/some/slug")

        mock_create.assert_called_once()
        data = mock_create.call_args[0][0]
        assert data.source_type is None
        assert data.source_id == "42"

    @patch("products.notifications.backend.facade.api.create_notification")
    def test_skips_self_mention(self, mock_create):
        comment = self._make_comment()
        send_mention_notifications(comment, [self.commenter.id], "/some/slug")

        mock_create.assert_not_called()

    @patch("products.notifications.backend.facade.api.create_notification")
    def test_no_commenter_returns_early(self, mock_create):
        comment = self._make_comment()
        comment.created_by = None
        send_mention_notifications(comment, [self.mentioned_user.id], "/some/slug")

        mock_create.assert_not_called()

from posthog.test.base import BaseTest
from unittest.mock import MagicMock

from posthog.models import OrganizationMembership, User
from posthog.permissions_guest import GuestAccessPermission


class TestGuestAccessPermission(BaseTest):
    def setUp(self):
        super().setUp()
        self.guest = User.objects.create_user(email="g@posthog.com", password="x", first_name="G")
        OrganizationMembership.objects.create(organization=self.organization, user=self.guest, is_guest=True)

    def _view(self, action: str, guest_enabled_actions: list[str]) -> MagicMock:
        v = MagicMock()
        v.action = action
        v.guest_enabled_actions = guest_enabled_actions
        return v

    def _request(self, user: User) -> MagicMock:
        r = MagicMock()
        r.user = user
        return r

    def test_non_guest_is_passthrough(self):
        perm = GuestAccessPermission()
        self.assertTrue(perm.has_permission(self._request(self.user), self._view("retrieve", [])))

    def test_guest_allowed_when_action_enabled(self):
        perm = GuestAccessPermission()
        self.assertTrue(perm.has_permission(self._request(self.guest), self._view("retrieve", ["retrieve"])))

    def test_guest_denied_when_action_not_enabled(self):
        perm = GuestAccessPermission()
        self.assertFalse(perm.has_permission(self._request(self.guest), self._view("create", ["retrieve"])))

    def test_guest_denied_when_no_guest_enabled_actions(self):
        perm = GuestAccessPermission()
        v = MagicMock(spec=[])
        v.action = "retrieve"
        self.assertFalse(perm.has_permission(self._request(self.guest), v))

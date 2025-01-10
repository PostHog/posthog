import pytest
from django.db.utils import IntegrityError

from posthog.test.base import BaseTest
from posthog.models.user_group import UserGroup, UserGroupMembership


class TestUserGroup(BaseTest):
    def test_user_group_membership_cascade_deletes(self):
        group = UserGroup.objects.create(project=self.project)
        UserGroupMembership.objects.create(group=group, user=self.user)

        assert UserGroupMembership.objects.count() == 1
        group.delete()
        assert UserGroupMembership.objects.count() == 0

    def test_user_group_membership_uniqueness(self):
        group = UserGroup.objects.create(project=self.project)
        with pytest.raises(IntegrityError):
            UserGroupMembership.objects.create(group=group, user=self.user)
            UserGroupMembership.objects.create(group=group, user=self.user)

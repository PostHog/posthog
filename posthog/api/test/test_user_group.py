from posthog.test.base import APIBaseTest
from posthog.models import UserGroup, UserGroupMembership


class TestUserGroup(APIBaseTest):
    def test_group_creation(self):
        self.client.post(
            f"/api/projects/{self.team.id}/user_groups",
            data={"name": "My team"},
        )
        user_group = UserGroup.objects.get(team=self.team)
        self.assertIsNotNone(user_group)
        self.assertEqual(user_group.name, "My team")

    def test_add_group_members(self):
        user_group = UserGroup.objects.create(team=self.team)
        self.client.post(
            f"/api/projects/{self.team.id}/user_groups/{user_group.id}/add",
            data={"userId": self.user.id},
        )
        self.assertEqual(user_group.members.count(), 1)

    def test_remove_group_members(self):
        user_group = UserGroup.objects.create(team=self.team)
        UserGroupMembership.objects.create(group=user_group, user=self.user)
        self.assertEqual(user_group.members.count(), 1)
        self.client.post(
            f"/api/projects/{self.team.id}/user_groups/{user_group.id}/remove",
            data={"userId": self.user.id},
        )
        self.assertEqual(user_group.members.count(), 0)

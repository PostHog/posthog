from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import UserPersonalization


class TestUserAvatarUrl(APIBaseTest):
    def test_can_set_and_remove_avatar_url(self) -> None:
        response = self.client.patch("/api/users/@me/", {"avatar_url": "https://example.com/me.png"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["avatar_url"], "https://example.com/me.png")
        self.assertEqual(
            UserPersonalization.objects.get(user=self.user).avatar_url,
            "https://example.com/me.png",
        )

        response = self.client.patch("/api/users/@me/", {"avatar_url": None})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["avatar_url"])
        self.assertIsNone(UserPersonalization.objects.get(user=self.user).avatar_url)

    def test_avatar_url_defaults_to_none_without_personalization_row(self) -> None:
        response = self.client.get("/api/users/@me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["avatar_url"])

    def test_rejects_non_https_avatar_url(self) -> None:
        for bad_url in ["http://example.com/me.png", "javascript:alert(1)", "not a url"]:
            response = self.client.patch("/api/users/@me/", {"avatar_url": bad_url})
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, bad_url)
        self.assertFalse(UserPersonalization.objects.filter(user=self.user).exists())

    def test_organization_members_expose_avatar_url(self) -> None:
        UserPersonalization.objects.create(user=self.user, avatar_url="https://example.com/me.png")
        response = self.client.get("/api/organizations/@current/members/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        member = next(m for m in response.json()["results"] if m["user"]["uuid"] == str(self.user.uuid))
        self.assertEqual(member["avatar_url"], "https://example.com/me.png")

from posthog.test.base import APIBaseTest

from rest_framework import status

from posthog.models import UserHomeSettings


class TestUserHomeSettingsAPI(APIBaseTest):
    def test_retrieve_empty_settings(self):
        response = self.client.get("/api/user_home_settings/@me/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "tabs": [],
                "homepage": None,
            },
        )

    def test_update_tabs_and_homepage(self):
        payload = {
            "tabs": [
                {
                    "id": "tab-1",
                    "pathname": "/a",
                    "search": "?q=1",
                    "hash": "#section",
                    "title": "Tab A",
                    "iconType": "blank",
                    "active": True,
                }
            ],
            "homepage": {
                "id": "home-1",
                "pathname": "/home",
                "search": "",
                "hash": "",
                "title": "Homepage",
                "iconType": "blank",
                "active": False,
            },
        }

        response = self.client.patch(
            "/api/user_home_settings/@me/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        expected_tab = {k: v for k, v in payload["tabs"][0].items() if k != "active"}
        expected_tab["pinned"] = True
        expected_homepage = {k: v for k, v in payload["homepage"].items() if k != "active"}
        expected_homepage["pinned"] = True

        self.assertEqual(
            response.json(),
            {
                "tabs": [expected_tab],
                "homepage": expected_homepage,
            },
        )

        stored = UserHomeSettings.objects.get(user=self.user, team=self.team)
        self.assertEqual(len(stored.tabs), 1)
        stored_tab = stored.tabs[0]
        self.assertEqual(stored_tab["id"], "tab-1")
        self.assertEqual(stored_tab["pinned"], True)
        self.assertNotIn("active", stored_tab)
        self.assertEqual(stored.homepage["id"], "home-1")
        self.assertEqual(stored.homepage["pinned"], True)

        self.assertFalse(UserHomeSettings.objects.filter(user=None, team=self.team).exists())

    def test_homepage_can_be_cleared(self):
        instance = UserHomeSettings.objects.create(
            user=self.user,
            team=self.team,
            tabs=[{"id": "tab-1", "pathname": "/a", "search": "", "hash": "", "title": "Tab A", "pinned": True}],
            homepage={"id": "tab-1", "pathname": "/a", "search": "", "hash": "", "title": "Tab A", "pinned": True},
        )

        response = self.client.patch(
            "/api/user_home_settings/@me/",
            {"homepage": None},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        instance.refresh_from_db()
        self.assertIsNone(instance.homepage)

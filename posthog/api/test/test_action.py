from freezegun import freeze_time
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    FuzzyInt,
    QueryMatchingTest,
    snapshot_postgres_queries_context,
)
from unittest.mock import ANY, patch

from rest_framework import status

from posthog.models import Action, Tag, User


class TestActionApi(ClickhouseTestMixin, APIBaseTest, QueryMatchingTest):
    @patch("posthog.api.action.report_user_action")
    def test_create_action(self, patch_capture, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={
                "name": "user signed up",
                "steps": [
                    {
                        "text": "sign up",
                        "selector": "div > button",
                        "url": "/signup",
                    }
                ],
                "description": "Test description",
            },
            HTTP_ORIGIN="http://testserver",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json() == {
            "id": ANY,
            "name": "user signed up",
            "description": "Test description",
            "post_to_slack": False,
            "slack_message_format": "",
            "steps": [
                {
                    "event": None,
                    "properties": None,
                    "selector": "div > button",
                    "tag_name": None,
                    "text": "sign up",
                    "text_matching": None,
                    "href": None,
                    "href_matching": None,
                    "url": "/signup",
                    "url_matching": "contains",
                }
            ],
            "created_at": ANY,
            "created_by": ANY,
            "pinned_at": None,
            "deleted": False,
            "creation_context": None,
            "is_calculating": False,
            "last_calculated_at": ANY,
            "team_id": self.team.id,
            "is_action": True,
            "bytecode_error": None,
            "tags": [],
            "user_access_level": "manager",
        }

        # Assert analytics are sent
        patch_capture.assert_called_once_with(
            self.user,
            "action created",
            {
                "post_to_slack": False,
                "name_length": 14,
                "custom_slack_message_format": False,
                "event_count_precalc": 0,
                "step_count": 1,
                "match_text_count": 1,
                "match_href_count": 0,
                "match_selector_count": 1,
                "match_url_count": 1,
                "has_properties": False,
                "deleted": False,
                "pinned": False,
                "pinned_at": None,
                "creation_context": None,
            },
        )

    def test_create_action_generates_bytecode(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={
                "name": "user signed up",
                "steps": [
                    {
                        "text": "sign up",
                        "selector": "div > button",
                        "url": "/signup",
                    }
                ],
                "description": "Test description",
            },
            HTTP_ORIGIN="http://testserver",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        action = Action.objects.get(pk=response.json()["id"])
        assert action.bytecode == ["_H", 1, 32, "%/signup%", 32, "$current_url", 32, "properties", 1, 2, 17]

    def test_cant_create_action_with_the_same_name(self, *args):
        original_action = Action.objects.create(name="user signed up", team=self.team)
        user2 = self._create_user("tim2")
        self.client.force_login(user2)

        count = Action.objects.count()

        # Make sure the endpoint works with and without the trailing slash
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            {"name": "user signed up"},
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "unique",
                "detail": f"This project already has an action with this name, ID {original_action.id}",
                "attr": "name",
            },
        )

        self.assertEqual(Action.objects.count(), count)

    @freeze_time("2021-12-12")
    @patch("posthog.api.action.report_user_action")
    def test_update_action(self, patch_capture, *args):
        user = self._create_user("test_user_update")
        self.client.force_login(user)

        action = Action.objects.create(
            name="user signed up", team=self.team, steps_json=[{"event": "$autocapture", "text": "sign me up!"}]
        )
        action.save()

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.pk}/",
            data={
                "name": "user signed up 2",
                "steps": [
                    {
                        "event": "$autocapture",
                        "text": "sign up NOW",
                        "selector": "div > button",
                        "properties": [{"key": "$browser", "value": "Chrome"}],
                        "url": None,
                    },
                    {"event": "$pageview", "href": "/a-new-link"},
                ],
                "description": "updated description",
                "created_by": {
                    "id": 1,
                    "distinct_id": "BLKJzxHq4z2d8P1icfpg5wo4eIHaSrMtnotkwdtD8Ok",
                    "first_name": "person",
                    "email": "person@email.com",
                },
                "pinned_at": "2021-12-11T00:00:00Z",
            },
            HTTP_ORIGIN="http://testserver",
        )
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["name"] == "user signed up 2"
        assert response.json()["description"] == "updated description"
        assert not response.json()["created_by"]
        assert response.json()["steps"] == [
            {
                "event": "$autocapture",
                "properties": [{"key": "$browser", "value": "Chrome"}],
                "selector": "div > button",
                "tag_name": None,
                "text": "sign up NOW",
                "text_matching": None,
                "href": None,
                "href_matching": None,
                "url": None,
                "url_matching": "contains",
            },
            {
                "event": "$pageview",
                "properties": None,
                "selector": None,
                "tag_name": None,
                "text": None,
                "text_matching": None,
                "href": "/a-new-link",
                "href_matching": None,
                "url": None,
                "url_matching": "contains",
            },
        ]

        action.refresh_from_db()
        assert action.name == "user signed up 2"

        # Assert analytics are sent
        patch_capture.assert_called_with(
            user,
            "action updated",
            {
                "post_to_slack": False,
                "name_length": 16,
                "custom_slack_message_format": False,
                "event_count_precalc": 0,
                "step_count": 2,
                "match_text_count": 1,
                "match_href_count": 1,
                "match_selector_count": 1,
                "match_url_count": 0,
                "has_properties": True,
                "updated_by_creator": False,
                "deleted": False,
                "pinned": True,
                "pinned_at": "2021-12-12T00:00:00+00:00",
            },
        )

        # test queries
        with self.assertNumQueries(FuzzyInt(9, 11)):
            # Django session,  user,  team,  org membership, instance setting,  org,
            # count, action
            self.client.get(f"/api/projects/{self.team.id}/actions/")

    def test_update_action_remove_all_steps(self, *args):
        action = Action.objects.create(name="user signed up", team=self.team, steps_json=[{"text": "sign me up!"}])

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.pk}/",
            data={"name": "user signed up 2", "steps": []},
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["steps"]), 0)

    # When we send a user to their own site, we give them a token.
    # Make sure you can only create actions if that token is set,
    # otherwise evil sites could create actions with a users' session.
    # NOTE: Origin header is only set on cross domain request
    def test_create_from_other_domain(self, *args):
        # FIXME: BaseTest is using Django client to perform calls to a DRF endpoint.
        # Django HttpResponse does not have an attribute `data`. Better use rest_framework.test.APIClient.
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={"name": "user signed up"},
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(response.status_code, 401)

        self.user.temporary_token = "token123"
        self.user.save()

        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/?temporary_token=token123",
            data={"name": "user signed up"},
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/?temporary_token=token123",
            data={"name": "user signed up and post to slack", "post_to_slack": True},
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["post_to_slack"], True)

        list_response = self.client.get(
            f"/api/projects/{self.team.id}/actions/",
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(list_response.status_code, 401)

        detail_response = self.client.get(
            f"/api/projects/{self.team.id}/actions/{response.json()['id']}/",
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(detail_response.status_code, 401)

        self.client.logout()
        list_response = self.client.get(
            f"/api/projects/{self.team.id}/actions/",
            data={"temporary_token": "token123"},
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(list_response.status_code, 200)

        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/?temporary_token=token123",
            data={"name": "user signed up 22"},
            HTTP_ORIGIN="https://somewebsite.com",
        )
        self.assertEqual(response.status_code, 201, response.json())

    # This case happens when someone is running behind a proxy, but hasn't set `IS_BEHIND_PROXY`
    def test_http_to_https(self, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={"name": "user signed up again"},
            HTTP_ORIGIN="https://testserver/",
        )
        self.assertEqual(response.status_code, 201, response.json())

    @patch("posthoganalytics.capture")
    def test_create_action_event_with_space(self, patch_capture, *args):
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={"name": "test event", "steps": [{"event": "test_event "}]},
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        action = Action.objects.get(pk=response.json()["id"])
        assert action.steps[0].event == "test_event "

    @freeze_time("2021-12-12")
    def test_listing_actions_is_not_nplus1(self) -> None:
        # Pre-query to cache things like instance settings
        self.client.get(f"/api/projects/{self.team.id}/actions/")

        with self.assertNumQueries(9), snapshot_postgres_queries_context(self):
            self.client.get(f"/api/projects/{self.team.id}/actions/")

        Action.objects.create(
            team=self.team,
            name="first",
            created_by=User.objects.create_and_join(self.organization, "a", ""),
        )

        with self.assertNumQueries(9), snapshot_postgres_queries_context(self):
            self.client.get(f"/api/projects/{self.team.id}/actions/")

        Action.objects.create(
            team=self.team,
            name="second",
            created_by=User.objects.create_and_join(self.organization, "b", ""),
        )

        with self.assertNumQueries(9), snapshot_postgres_queries_context(self):
            self.client.get(f"/api/projects/{self.team.id}/actions/")

    def test_get_tags_on_non_ee_returns_empty_list(self):
        action = Action.objects.create(team=self.team, name="bla")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        action.tagged_items.create(tag_id=tag.id)

        response = self.client.get(f"/api/projects/{self.team.id}/actions/{action.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], [])
        self.assertEqual(Action.objects.all().count(), 1)

    def test_create_tags_on_non_ee_not_allowed(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            {"name": "Default", "tags": ["random", "hello"]},
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["tags"], [])
        self.assertEqual(Tag.objects.all().count(), 0)

    def test_update_tags_on_non_ee_not_allowed(self):
        action = Action.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        action.tagged_items.create(tag_id=tag.id)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.id}",
            {
                "name": "action new name",
                "tags": ["random", "hello"],
                "description": "Internal system metrics.",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], [])

    def test_undefined_tags_allows_other_props_to_update(self):
        action = Action.objects.create(team_id=self.team.id, name="private action")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        action.tagged_items.create(tag_id=tag.id)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.id}",
            {"name": "action new name", "description": "Internal system metrics."},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "action new name")
        self.assertEqual(response.json()["description"], "Internal system metrics.")

    def test_empty_tags_does_not_delete_tags(self):
        action = Action.objects.create(team_id=self.team.id, name="private dashboard")
        tag = Tag.objects.create(name="random", team_id=self.team.id)
        action.tagged_items.create(tag_id=tag.id)

        self.assertEqual(Action.objects.all().count(), 1)

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.id}",
            {
                "name": "action new name",
                "description": "Internal system metrics.",
                "tags": [],
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["tags"], [])
        self.assertEqual(Tag.objects.all().count(), 1)

    def test_hard_deletion_is_forbidden(self):
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={
                "name": "user signed up",
                "steps": [
                    {
                        "text": "sign up",
                        "selector": "div > button",
                        "url": "/signup",
                        "isNew": "asdf",
                    }
                ],
                "description": "Test description",
            },
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        deletion_response = self.client.delete(f"/api/projects/{self.team.id}/actions/{response.json()['id']}")
        self.assertEqual(deletion_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_create_action_in_specific_folder(self):
        """
        Verify that creating an Action with '_create_in_folder' stores its FileSystem entry
        under the specified folder.
        """
        # 1. Create an Action, passing `_create_in_folder`
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={
                "name": "user signed up in folder",
                "_create_in_folder": "Special Folder/Actions",
            },
            HTTP_ORIGIN="http://testserver",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()

        action_id = response.json()["id"]
        assert action_id is not None

        # 2. Verify the FileSystem entry
        from posthog.models.file_system.file_system import FileSystem

        fs_entry = FileSystem.objects.filter(team=self.team, ref=str(action_id), type="action").first()
        assert fs_entry is not None, "A FileSystem entry was not created for this Action."
        assert (
            "Special Folder/Actions" in fs_entry.path
        ), f"Expected folder to include 'Special Folder/Actions' but got '{fs_entry.path}'."

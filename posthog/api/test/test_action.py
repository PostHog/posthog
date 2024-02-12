import json
from unittest.mock import patch

from freezegun import freeze_time
from rest_framework import status

from posthog.models import Action, ActionStep, Organization, Tag, User
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    QueryMatchingTest,
    _create_event,
    snapshot_postgres_queries_context,
    FuzzyInt,
)


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
                        "isNew": "asdf",
                    }
                ],
                "description": "Test description",
            },
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()["is_calculating"], False)
        self.assertIn("last_calculated_at", response.json())
        action = Action.objects.get()
        self.assertEqual(action.name, "user signed up")
        self.assertEqual(action.description, "Test description")
        self.assertEqual(action.team, self.team)
        self.assertEqual(action.steps.get().selector, "div > button")
        self.assertEqual(response.json()["steps"][0]["text"], "sign up")
        self.assertEqual(response.json()["steps"][0]["url"], "/signup")
        self.assertNotIn("isNew", response.json()["steps"][0])

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
            },
        )

    def test_cant_create_action_with_the_same_name(self, *args):
        original_action = Action.objects.create(name="user signed up", team=self.team)
        user2 = self._create_user("tim2")
        self.client.force_login(user2)

        count = Action.objects.count()
        steps_count = ActionStep.objects.count()

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
        self.assertEqual(ActionStep.objects.count(), steps_count)

    @patch("posthog.api.action.report_user_action")
    def test_update_action(self, patch_capture, *args):
        user = self._create_user("test_user_update")
        self.client.force_login(user)

        action = Action.objects.create(name="user signed up", team=self.team)
        ActionStep.objects.create(action=action, text="sign me up!")
        action_id = action.steps.get().pk
        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.pk}/",
            data={
                "name": "user signed up 2",
                "steps": [
                    {
                        "id": action_id,
                        "isNew": "asdf",
                        "text": "sign up NOW",
                        "selector": "div > button",
                        "properties": [{"key": "$browser", "value": "Chrome"}],
                        "url": None,
                    },
                    {"href": "/a-new-link"},
                ],
                "description": "updated description",
                "created_by": {
                    "id": 1,
                    "distinct_id": "BLKJzxHq4z2d8P1icfpg5wo4eIHaSrMtnotkwdtD8Ok",
                    "first_name": "person",
                    "email": "person@email.com",
                },
            },
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["name"], "user signed up 2")
        self.assertEqual(response.json()["created_by"], None)
        self.assertEqual(response.json()["steps"][0]["id"], str(action_id))
        self.assertEqual(response.json()["steps"][1]["href"], "/a-new-link")
        self.assertEqual(response.json()["description"], "updated description")

        action.refresh_from_db()
        steps = action.steps.all().order_by("id")
        self.assertEqual(action.name, "user signed up 2")
        self.assertEqual(steps[0].text, "sign up NOW")
        self.assertEqual(steps[1].href, "/a-new-link")

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
            },
        )

        # test queries
        with self.assertNumQueries(FuzzyInt(7, 8)):
            # Django session, PostHog user, PostHog team, PostHog org membership, PostHog org
            # PostHog action, PostHog action step
            self.client.get(f"/api/projects/{self.team.id}/actions/")

    def test_update_action_remove_all_steps(self, *args):
        action = Action.objects.create(name="user signed up", team=self.team)
        ActionStep.objects.create(action=action, text="sign me up!")

        response = self.client.patch(
            f"/api/projects/{self.team.id}/actions/{action.pk}/",
            data={"name": "user signed up 2", "steps": []},
            HTTP_ORIGIN="http://testserver",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["steps"]), 0)
        self.assertEqual(ActionStep.objects.count(), 0)

    # When we send a user to their own site, we give them a token.
    # Make sure you can only create actions if that token is set,
    # otherwise evil sites could create actions with a users' session.
    # NOTE: Origin header is only set on cross domain request
    def test_create_from_other_domain(self, *args):
        # FIXME: BaseTest is using Django client to performe calls to a DRF endpoint.
        # Django HttpResponse does not have an attribute `data`. Better use rest_framework.test.APIClient.
        response = self.client.post(
            f"/api/projects/{self.team.id}/actions/",
            data={"name": "user signed up"},
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(response.status_code, 403)

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
        self.assertEqual(list_response.status_code, 403)

        detail_response = self.client.get(
            f"/api/projects/{self.team.id}/actions/{response.json()['id']}/",
            HTTP_ORIGIN="https://evilwebsite.com",
        )
        self.assertEqual(detail_response.status_code, 403)

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
        action = Action.objects.get()
        self.assertEqual(action.steps.get().event, "test_event ")

    @freeze_time("2021-12-12")
    def test_get_event_count(self, *args):
        team2 = Organization.objects.bootstrap(None, team_fields={"name": "bla"})[2]
        action = Action.objects.create(team=self.team, name="bla")
        ActionStep.objects.create(action=action, event="custom event")
        _create_event(
            event="custom event",
            team=self.team,
            distinct_id="test",
            timestamp="2021-12-04T19:20:00Z",
        )
        _create_event(
            event="another event",
            team=self.team,
            distinct_id="test",
            timestamp="2021-12-04T19:20:00Z",
        )
        # test team leakage
        _create_event(
            event="custom event",
            team=team2,
            distinct_id="test",
            timestamp="2021-12-04T19:20:00Z",
        )

        response = self.client.get(f"/api/projects/{self.team.id}/actions/{action.id}/count").json()
        self.assertEqual(response, {"count": 1})

    @freeze_time("2021-12-10")
    def test_hogql_filter(self, *args):
        action = Action.objects.create(team=self.team, name="bla")
        ActionStep.objects.create(
            action=action,
            event="custom event",
            properties=[{"key": "'a%sd' != 'sdf'", "type": "hogql"}],
        )
        _create_event(
            event="custom event",
            team=self.team,
            distinct_id="test",
            timestamp="2021-12-04T19:20:00Z",
        )
        _create_event(
            event="another event",
            team=self.team,
            distinct_id="test",
            timestamp="2021-12-04T19:21:00Z",
        )

        # action count
        response = self.client.get(f"/api/projects/{self.team.id}/actions/{action.id}/count").json()
        self.assertEqual(response, {"count": 1})
        # events list
        response = self.client.get(f"/api/projects/{self.team.id}/events/?action_id={action.id}").json()
        self.assertEqual(len(response["results"]), 1)
        # trends insight
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?actions={json.dumps([{'type': 'actions', 'id': action.id}])}"
        ).json()
        self.assertEqual(response["result"][0]["count"], 1)

    @freeze_time("2021-12-10")
    def test_hogql_filter_no_event(self, *args):
        action = Action.objects.create(team=self.team, name="bla")
        ActionStep.objects.create(
            action=action,
            event=None,
            properties=[{"key": "event like 'blue %'", "type": "hogql"}],
        )
        _create_event(
            event="blue event",
            team=self.team,
            distinct_id="test",
            timestamp="2021-12-04T19:20:00Z",
        )
        _create_event(
            event="green event",
            team=self.team,
            distinct_id="test",
            timestamp="2021-12-04T19:21:00Z",
        )

        # action count
        response = self.client.get(f"/api/projects/{self.team.id}/actions/{action.id}/count").json()
        self.assertEqual(response, {"count": 1})
        # events list
        response = self.client.get(f"/api/projects/{self.team.id}/events/?action_id={action.id}").json()
        self.assertEqual(len(response["results"]), 1)
        # trends insight
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/trend/?actions={json.dumps([{'type': 'actions', 'id': action.id}])}"
        ).json()
        self.assertEqual(response["result"][0]["count"], 1)

    @freeze_time("2021-12-12")
    def test_listing_actions_is_not_nplus1(self) -> None:
        with self.assertNumQueries(7), snapshot_postgres_queries_context(self):
            self.client.get(f"/api/projects/{self.team.id}/actions/")

        Action.objects.create(
            team=self.team,
            name="first",
            created_by=User.objects.create_and_join(self.organization, "a", ""),
        )

        with self.assertNumQueries(7), snapshot_postgres_queries_context(self):
            self.client.get(f"/api/projects/{self.team.id}/actions/")

        Action.objects.create(
            team=self.team,
            name="second",
            created_by=User.objects.create_and_join(self.organization, "b", ""),
        )

        with self.assertNumQueries(7), snapshot_postgres_queries_context(self):
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

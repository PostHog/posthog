from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.core.cache.backends.locmem import LocMemCache

from parameterized import parameterized

from posthog.api.tag_definition import TagMutationBurstRateThrottle, TagMutationSustainedRateThrottle
from posthog.api.tagged_item import apply_bulk_tag_changes
from posthog.constants import INTERNAL_BOT_EMAIL_SUFFIX
from posthog.models import OrganizationMembership, PersonalAPIKey, Tag, Team, User
from posthog.rate_limit import PersonalApiKeyOrUserRateThrottle
from posthog.tag_management import merge_tags
from posthog.utils import feature_flag_bootstrap

from products.dashboards.backend.models.dashboard import Dashboard


class TestTagDefinitions(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.membership = OrganizationMembership.objects.get(user=self.user, organization=self.organization)
        self.membership.level = OrganizationMembership.Level.ADMIN
        self.membership.save()
        self.flag = patch("posthog.tag_management_access.posthoganalytics.feature_enabled", return_value=True)
        self.evaluate_flag = self.flag.start()
        self.addCleanup(self.flag.stop)
        self.url = f"/api/projects/{self.team.id}/tag_definitions/"
        self.source = Tag.objects.create(team=self.team, name="customers")
        self.target = Tag.objects.create(team=self.team, name="customer")

    def test_list_search_order_pagination_and_system_exclusion(self) -> None:
        Tag.objects.create(team=self.team, name="project-group:internal")
        other = Team.objects.create(organization=self.organization)
        Tag.objects.create(team=other, name="other")
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard", deleted=True)
        dashboard.tagged_items.create(tag=self.target)
        params: dict[str, str | int] = {"search": "customer", "ordering": "-usage_count", "limit": 1}
        response = self.client.get(self.url, params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(
            response.json()["results"], [{"id": str(self.target.id), "name": "customer", "usage_count": 1}]
        )
        self.assertIsNotNone(response.json()["next"])

    def test_usage_order_breaks_ties_by_name_across_pages(self) -> None:
        Tag.objects.create(team=self.team, name="aardvark")
        params: dict[str, str | int] = {"ordering": "-usage_count", "limit": 1}
        names = [
            self.client.get(self.url, {**params, "offset": offset}).json()["results"][0]["name"] for offset in range(3)
        ]
        self.assertEqual(names, ["aardvark", "customer", "customers"])

    @parameterized.expand(["get", "patch", "delete", "preview", "merge"])
    def test_flag_off_rejects_every_management_operation(self, operation: str) -> None:
        with patch("posthog.tag_management_access.posthoganalytics.feature_enabled", return_value=False):
            self.assertEqual(self._request(operation).status_code, 404)
        self.assertTrue(Tag.objects.filter(id=self.source.id).exists())

    def test_flag_targeting_matches_the_bootstrap_for_child_environment(self) -> None:
        environment = Team.objects.create(
            organization=self.organization, project_id=self.team.project_id, name="Child environment"
        )
        self.user.current_team = environment
        self.user.save(update_fields=["current_team"])
        inactive = User.objects.create_user(
            email="inactive@example.com", password=None, first_name="Inactive", is_active=False
        )
        bot = User.objects.create_user(email=f"example{INTERNAL_BOT_EMAIL_SUFFIX}", password=None, first_name="Bot")
        for extra_user in [inactive, bot]:
            OrganizationMembership.objects.create(organization=self.organization, user=extra_user)

        invisible = Team.objects.create(organization=self.organization, name="Hidden project")
        from posthog.api.organization import filter_projects

        with (
            patch(
                "posthog.api.organization.filter_projects",
                side_effect=lambda queryset, **kwargs: filter_projects(queryset, **kwargs).exclude(id=invisible.id),
            ),
            patch("posthog.utils.posthoganalytics.feature_flag_definitions", return_value=[]),
            patch("posthog.utils.app_flag_keys", return_value=["tag-management"]),
            patch(
                "posthog.utils.posthoganalytics.get_all_flags", return_value={"tag-management": True}
            ) as bootstrap_flags,
        ):
            current_user = self.client.get("/api/users/@me/").json()
            self.assertEqual(current_user["team"]["id"], environment.id)
            self.assertNotIn(invisible.id, [team["id"] for team in current_user["organization"]["teams"]])
            self.assertLess(current_user["organization"]["member_count"], self.organization.members.count())
            feature_flag_bootstrap(self.user, current_user)
            self.assertEqual(
                self.client.get(self.url, HTTP_X_POSTHOG_ENVIRONMENT_ID=str(environment.id)).status_code, 200
            )

        expected = bootstrap_flags.call_args.kwargs
        actual = self.evaluate_flag.call_args.kwargs
        self.assertEqual(actual["groups"], expected["groups"])
        self.assertEqual(actual["group_properties"], expected["group_properties"])

    @parameterized.expand(["get", "patch", "delete", "preview", "merge"])
    def test_tab_environment_survives_another_tabs_environment_switch(self, operation: str) -> None:
        environment = Team.objects.create(organization=self.organization, project_id=self.team.project_id)
        self.assertEqual(self.client.get("/api/users/@me/").json()["team"]["id"], self.team.id)
        self.user.current_team = environment
        self.user.save(update_fields=["current_team"])
        self.evaluate_flag.side_effect = lambda *args, **kwargs: kwargs["groups"]["project"] == str(self.team.uuid)
        self.client.credentials(HTTP_X_POSTHOG_ENVIRONMENT_ID=str(self.team.id))

        response = self._request(operation)

        self.assertEqual(response.status_code, 204 if operation == "delete" else 200)
        self.assertEqual(self.evaluate_flag.call_args.kwargs["groups"]["project"], str(self.team.uuid))

    def test_tab_environment_must_belong_to_the_requested_project(self) -> None:
        other = Team.objects.create(organization=self.organization)

        response = self.client.get(self.url, HTTP_X_POSTHOG_ENVIRONMENT_ID=str(other.id))

        self.assertEqual(response.status_code, 404)
        self.evaluate_flag.assert_not_called()

    @parameterized.expand(["get", "patch", "delete", "preview", "merge"])
    def test_member_cannot_manage_tags(self, operation: str) -> None:
        self.membership.level = OrganizationMembership.Level.MEMBER
        self.membership.save()
        self.assertEqual(self._request(operation).status_code, 403)

    @parameterized.expand(
        [
            (throttle_class, operation)
            for throttle_class in [TagMutationBurstRateThrottle, TagMutationSustainedRateThrottle]
            for operation in ["patch", "delete", "merge"]
        ]
    )
    def test_session_mutation_limits_leave_reads_available(
        self, throttle_class: type[PersonalApiKeyOrUserRateThrottle], operation: str
    ) -> None:
        with (
            patch("posthog.rate_limit.is_rate_limit_enabled", return_value=True),
            patch.object(PersonalApiKeyOrUserRateThrottle, "cache", LocMemCache(f"tag-mutation-{uuid4()}", {})),
            patch.object(throttle_class, "rate", "1/minute"),
        ):
            self.assertEqual(self._request(operation).status_code, 204 if operation == "delete" else 200)
            self.assertEqual(self._request(operation).status_code, 429)
            self.assertEqual(self.client.get(self.url).status_code, 200)

    @parameterized.expand(["get", "patch", "delete", "preview", "merge"])
    def test_personal_api_keys_cannot_manage_tags(self, operation: str) -> None:
        PersonalAPIKey.objects.create(user=self.user, label="test", secure_value="tag-management-test", scopes=["*"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION="Bearer tag-management-test")
        self.assertIn(self._request(operation).status_code, [401, 403])

    def _request(self, operation: str):
        detail = f"{self.url}{self.source.id}/"
        if operation == "patch":
            return self.client.patch(detail, {"name": "renamed"})
        if operation == "delete":
            return self.client.delete(detail)
        if operation == "preview":
            return self.client.get(f"{detail}merge_preview/", {"target_id": str(self.target.id)})
        if operation == "merge":
            return self.client.post(f"{detail}merge/", {"target_id": str(self.target.id)})
        return self.client.get(self.url)

    def test_create_is_not_supported(self) -> None:
        response = self.client.post(self.url, {"name": "new"})
        self.assertEqual(response.status_code, 405)
        self.assertFalse(Tag.objects.filter(name="new").exists())

    def test_bulk_add_discards_tags_prefetched_before_merge(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=self.source)

        def merge_after_prefetch(objects, *args, **kwargs):
            for obj in objects:
                obj.prefetched_tags = list(obj.tagged_items.select_related("tag"))
                self.assertEqual([item.tag_id for item in obj.prefetched_tags], [self.source.id])
            merge_tags(self.team.id, self.source.id, self.target.id, self.user)
            return apply_bulk_tag_changes(objects, *args, **kwargs)

        with patch("posthog.api.tagged_item.apply_bulk_tag_changes", side_effect=merge_after_prefetch):
            response = self.client.post(
                f"/api/projects/{self.team.id}/dashboards/bulk_update_tags/",
                {"ids": [dashboard.id], "action": "add", "tags": ["extra"]},
            )

        self.assertEqual(response.status_code, 200, response.json())
        self.assertEqual(response.json()["updated"][0]["tags"], ["customer", "extra"])
        self.assertTrue(dashboard.tagged_items.filter(tag=self.target).exists())
        self.assertFalse(Tag.objects.filter(team_id=self.team.id, name=self.source.name).exists())

    def test_detail_reads_current_tag_by_id_after_merge(self) -> None:
        source_url = f"{self.url}{self.source.id}/"
        self.assertEqual(self.client.get(source_url).json()["name"], self.source.name)
        self.assertEqual(self._request("merge").status_code, 200)
        self.assertEqual(self.client.get(source_url).status_code, 404)
        self.assertEqual(self.client.get(f"{self.url}{self.target.id}/").json()["id"], str(self.target.id))

    def test_rename_normalization_and_collision(self) -> None:
        detail = f"{self.url}{self.source.id}/"
        self.assertEqual(self.client.patch(detail, {"name": "  CUSTOMER  "}).status_code, 400)
        response = self.client.patch(detail, {"name": "  New name  "})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "new name")

    def test_rename_requires_a_name(self) -> None:
        self.assertEqual(self.client.patch(f"{self.url}{self.source.id}/", {}).status_code, 400)
        self.source.refresh_from_db()
        self.assertEqual(self.source.name, "customers")

    @parameterized.expand(["project-group:internal", "", "  "])
    def test_rename_cannot_create_reserved_or_blank_names(self, name: str) -> None:
        self.assertEqual(self.client.patch(f"{self.url}{self.source.id}/", {"name": name}).status_code, 400)

    def test_delete_rechecks_usage(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=self.source)
        self.assertEqual(self.client.delete(f"{self.url}{self.source.id}/").status_code, 400)
        self.assertTrue(dashboard.tagged_items.filter(tag=self.source).exists())
        self.assertEqual(self.client.delete(f"{self.url}{self.target.id}/").status_code, 204)

    def test_merge_returns_actual_outcome_after_preview(self) -> None:
        detail = f"{self.url}{self.source.id}/"
        response = self.client.get(f"{detail}merge_preview/", {"target_id": str(self.target.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["source_count"], 0)
        dashboard = Dashboard.objects.create(team=self.team, name="dashboard")
        dashboard.tagged_items.create(tag=self.source)
        response = self.client.post(f"{detail}merge/", {"target_id": str(self.target.id)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["moved_count"], 1)
        self.assertEqual(response.json()["usage_count"], 1)
        self.assertFalse(Tag.objects.filter(id=self.source.id).exists())

    @parameterized.expand(["missing", "cross_team", "system"])
    def test_invalid_destination_never_changes_source(self, kind: str) -> None:
        target_id = uuid4()
        if kind == "cross_team":
            team = Team.objects.create(organization=self.organization)
            target_id = Tag.objects.create(team=team, name="other").id
        elif kind == "system":
            target_id = Tag.objects.create(team=self.team, name="project-group:internal").id
        response = self.client.post(f"{self.url}{self.source.id}/merge/", {"target_id": str(target_id)})
        self.assertIn(response.status_code, [400, 404])
        self.assertTrue(Tag.objects.filter(id=self.source.id).exists())

    def test_unauthenticated_access_is_denied(self) -> None:
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_flag_evaluation_failure_fails_closed(self) -> None:
        with patch(
            "posthog.tag_management_access.posthoganalytics.feature_enabled", side_effect=RuntimeError("unavailable")
        ):
            self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_source_id_from_another_project_is_not_found(self) -> None:
        other = Team.objects.create(organization=self.organization)
        tag = Tag.objects.create(team=other, name="other")
        self.assertEqual(self.client.patch(f"{self.url}{tag.id}/", {"name": "renamed"}).status_code, 404)
        self.assertEqual(self.client.delete(f"{self.url}{tag.id}/").status_code, 404)
        self.assertEqual(
            self.client.post(f"{self.url}{tag.id}/merge/", {"target_id": str(self.target.id)}).status_code, 404
        )
        tag.refresh_from_db()
        self.assertEqual(tag.name, "other")

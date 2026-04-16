from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Optional

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.db.models import Q

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import User
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.dashboards.backend.api.dashboard_templates import (
    MAX_DASHBOARD_TEMPLATES_PER_ORGANIZATION,
    organization_dashboard_template_limit_detail,
)
from products.dashboards.backend.models.dashboard_templates import DashboardTemplate

from ee.models.rbac.access_control import AccessControl


def assert_template_equals(received, expected):
    keys_to_check = [
        "template_name",
        "dashboard_description",
        "tags",
        "variables",
        "tiles",
        "dashboard_filters",
    ]

    for key in keys_to_check:
        assert received[key] == expected[key], f"key {key} failed, expected {expected[key]} but got {received[key]}"


def get_template_from_response(response, id):
    for template in response.json()["results"]:
        if template["id"] == str(id):
            return template
    return None


def ensure_baseline_global_dashboard_templates() -> None:
    """Ensure the two named global team-less seeds tests rely on (don't use total row count — other fixtures may fill the table)."""
    if not DashboardTemplate.objects.filter(
        template_name="Product analytics",
        team_id__isnull=True,
        scope=DashboardTemplate.Scope.GLOBAL,
    ).exists():
        og = DashboardTemplate.original_template()
        og.team_id = None
        og.scope = DashboardTemplate.Scope.GLOBAL
        og.save()
    if not DashboardTemplate.objects.filter(
        template_name="Flagged Feature Usage",
        team_id__isnull=True,
        scope=DashboardTemplate.Scope.GLOBAL,
    ).exists():
        DashboardTemplate.objects.create(
            team_id=None,
            scope=DashboardTemplate.Scope.GLOBAL,
            template_name="Flagged Feature Usage",
            dashboard_description="Overview of engagement with the flagged feature including daily active users and weekly active users.",
            dashboard_filters={},
            tiles=variable_template["tiles"],
            variables=[],
            tags=[],
        )


def _listable_dashboard_template_db_count(team_pk: int) -> int:
    """Rows visible on default dashboard_templates list (mirrors `dangerously_get_queryset` without scope=)."""
    return DashboardTemplate.objects.filter(Q(scope=DashboardTemplate.Scope.GLOBAL) | Q(team_id=team_pk)).count()


variable_template = {
    "template_name": "Sign up conversion template with variables",
    "dashboard_description": "Use this template to see how many users sign up after visiting your pricing page.",
    "dashboard_filters": {},
    "tiles": [
        {
            "name": "Website Unique Users (Total)",
            "type": "INSIGHT",
            "color": "blue",
            "filters": {
                "events": ["{VARIABLE_1}"],
                "compare": True,
                "display": "BoldNumber",
                "insight": "TRENDS",
                "interval": "day",
                "date_from": "-30d",
            },
            "layouts": {
                "sm": {"h": 5, "i": "21", "w": 6, "x": 0, "y": 0, "minH": 5, "minW": 3},
                "xs": {"h": 5, "i": "21", "w": 1, "x": 0, "y": 0, "minH": 5, "minW": 1},
            },
            "description": "Shows the number of unique users that use your app every day.",
        },
    ],
    "tags": ["popular"],
    "variables": [
        {
            "id": "VARIABLE_1",
            "name": "Page view on your website",
            "description": "The event that is triggered when a user visits a page on your site",
            "type": "event",
            "default": {"id": "$pageview", "math": "dau", "type": "events"},
            "required": True,
        },
        {
            "id": "VARIABLE_2",
            "name": "Sign up event",
            "description": "The event that is triggered when a user signs up",
            "type": "event",
            "default": {"id": "$autocapture", "math": "dau", "type": "events"},
            "required": False,
        },
    ],
}


class TestDashboardTemplates(APIBaseTest):
    def setUp(self):
        super().setUp()

        self.user.is_staff = True
        self.user.save()
        ensure_baseline_global_dashboard_templates()

    def test_create_rejects_when_organization_has_max_dashboard_templates(self) -> None:
        seed_tiles = variable_template["tiles"]
        DashboardTemplate.objects.bulk_create(
            [
                DashboardTemplate(
                    team_id=self.team.pk,
                    template_name=f"org-cap-fill-{i}",
                    scope=DashboardTemplate.Scope.ONLY_TEAM,
                    dashboard_description="",
                    dashboard_filters={},
                    tiles=seed_tiles,
                    variables=[],
                    tags=[],
                )
                for i in range(MAX_DASHBOARD_TEMPLATES_PER_ORGANIZATION)
            ]
        )

        overflow = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {**variable_template, "template_name": "over the limit template"},
        )
        assert overflow.status_code == status.HTTP_400_BAD_REQUEST, overflow.content
        assert overflow.json()["detail"] == organization_dashboard_template_limit_detail()

    def test_restore_rejects_when_organization_already_has_max_dashboard_templates(self) -> None:
        seed_tiles = variable_template["tiles"]
        DashboardTemplate.objects.bulk_create(
            [
                DashboardTemplate(
                    team_id=self.team.pk,
                    template_name=f"org-cap-restore-{i}",
                    scope=DashboardTemplate.Scope.ONLY_TEAM,
                    dashboard_description="",
                    dashboard_filters={},
                    tiles=seed_tiles,
                    variables=[],
                    tags=[],
                )
                for i in range(MAX_DASHBOARD_TEMPLATES_PER_ORGANIZATION - 1)
            ]
        )

        victim = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {**variable_template, "template_name": "victim to delete"},
        )
        assert victim.status_code == status.HTTP_201_CREATED, victim.content
        victim_id = victim.json()["id"]

        assert (
            self.client.patch(
                f"/api/projects/{self.team.pk}/dashboard_templates/{victim_id}",
                {"deleted": True},
            ).status_code
            == status.HTTP_200_OK
        )

        replacement = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {**variable_template, "template_name": "replacement while victim deleted"},
        )
        assert replacement.status_code == status.HTTP_201_CREATED, replacement.content

        blocked_restore = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{victim_id}",
            {"deleted": False},
        )
        assert blocked_restore.status_code == status.HTTP_400_BAD_REQUEST, blocked_restore.content
        assert blocked_restore.json()["detail"] == organization_dashboard_template_limit_detail()

    def test_create_and_get_dashboard_template_with_tile(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        dashboard_template = DashboardTemplate.objects.get(id=response.json()["id"])
        assert dashboard_template.team_id == self.team.pk

        assert_template_equals(
            dashboard_template.__dict__,
            variable_template,
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert response.status_code == status.HTTP_200_OK, response

        assert_template_equals(
            get_template_from_response(response, dashboard_template.id),
            variable_template,
        )

        assert get_template_from_response(response, dashboard_template.id)["team_id"] == self.team.pk

    def test_create_dashboard_template_duplicate_name_returns_bad_request(self) -> None:
        # create first template
        self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )

        # create second template
        duplicate_response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )

        assert duplicate_response.status_code == status.HTTP_400_BAD_REQUEST, duplicate_response
        assert (
            duplicate_response.json()["detail"]
            == "A dashboard template with this name already exists for this project."
        )

    def test_create_dashboard_template_duplicate_name_for_soft_deleted(self) -> None:
        n0 = DashboardTemplate.objects_including_soft_deleted.count()
        # create first template (soft deleted)
        self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {**variable_template, "deleted": True},
        )

        # create second template
        duplicate_response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )

        assert duplicate_response.status_code == status.HTTP_201_CREATED, duplicate_response
        assert DashboardTemplate.objects_including_soft_deleted.count() == n0 + 2

    @parameterized.expand(
        [
            ("team", "Featured team template"),
            ("global", "Featured global template"),
        ]
    )
    def test_is_featured_can_be_set_on_creation(self, scope: str, template_name: str) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {**variable_template, "template_name": template_name, "scope": scope, "is_featured": True},
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert response.json()["is_featured"] is True
        assert response.json()["scope"] == scope

    def test_is_featured_defaults_to_false_when_omitted(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {**variable_template, "template_name": "Template without is_featured"},
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert response.json()["is_featured"] is False

    def test_is_featured_persists_when_scope_changes_to_team(self) -> None:
        global_featured = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {
                **variable_template,
                "template_name": "Featured global then team scope",
                "scope": "global",
                "is_featured": True,
            },
        )
        assert global_featured.status_code == status.HTTP_201_CREATED, global_featured
        assert global_featured.json()["is_featured"] is True

        patch = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{global_featured.json()['id']}",
            {"scope": "team"},
        )
        assert patch.status_code == status.HTTP_200_OK, patch
        assert patch.json()["is_featured"] is True

    def test_staff_can_make_dashboard_template_public(self) -> None:
        assert self.team.pk is not None
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert response.json()["scope"] == "team"

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"scope": "global"},
        )

        assert update_response.status_code == status.HTTP_200_OK, update_response

        get_updated_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_updated_response.status_code == status.HTTP_200_OK, get_updated_response

        assert get_updated_response.json()["results"][0]["scope"] == "global"

    def test_staff_can_make_dashboard_template_private(self) -> None:
        assert self.team.pk is not None
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        id = response.json()["id"]

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{id}",
            {"scope": "global"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response

        get_updated_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_updated_response.status_code == status.HTTP_200_OK, get_updated_response

        assert get_template_from_response(get_updated_response, id)["scope"] == "global"

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{id}",
            {"scope": "team"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response

        get_updated_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_updated_response.status_code == status.HTTP_200_OK, get_updated_response

        assert get_template_from_response(get_updated_response, id)["scope"] == "team"

    def test_staff_can_narrow_built_in_style_global_template_to_current_team(self) -> None:
        tpl = DashboardTemplate.objects.create(
            team_id=None,
            scope=DashboardTemplate.Scope.GLOBAL,
            template_name="Staff narrow global null-team fixture",
            dashboard_description="",
            dashboard_filters={},
            tiles=variable_template["tiles"],
            variables=[],
            tags=[],
        )

        response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{tpl.id}",
            {"scope": "team"},
        )
        assert response.status_code == status.HTTP_200_OK, response
        body = response.json()
        assert body["scope"] == "team"
        assert body["team_id"] == self.team.pk

        tpl.refresh_from_db()
        assert tpl.scope == DashboardTemplate.Scope.ONLY_TEAM
        assert tpl.team_id == self.team.pk

    def test_non_staff_cannot_make_dashboard_template_public(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response

        self.user.is_staff = False
        self.user.save()

        with patch(
            "products.dashboards.backend.api.dashboard_templates.posthoganalytics.feature_enabled",
            return_value=True,
        ):
            update_response = self.client.patch(
                f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
                {"scope": "global"},
            )
        assert update_response.status_code == status.HTTP_400_BAD_REQUEST, update_response

    def test_non_staff_cannot_edit_dashboard_template(self) -> None:
        default_template = DashboardTemplate.objects.all()[0]
        assert default_template.scope == "global"

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{default_template.id}",
            {"template_name": "Test name"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response

        self.user.is_staff = False
        self.user.save()

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{default_template.id}",
            {"template_name": "Test name"},
        )
        assert update_response.status_code == status.HTTP_403_FORBIDDEN, update_response

    def test_non_staff_can_get_public_dashboard_templates(self) -> None:
        global_seed_count = DashboardTemplate.objects.filter(scope=DashboardTemplate.Scope.GLOBAL).count()
        assert self.team.pk is not None
        new_org = Organization.objects.create(name="Test Org 2")
        new_team = Team.objects.create(name="Test Team 2", organization=new_org)
        dashboard_template = DashboardTemplate.objects.create(
            team_id=new_team.pk,
            scope=DashboardTemplate.Scope.ONLY_TEAM,
            **variable_template,
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/")
        assert response.status_code == status.HTTP_200_OK, response

        assert len(response.json()["results"]) == global_seed_count  # Other org template is team-scoped elsewhere

        dashboard_template.scope = "global"
        dashboard_template.save()

        get_updated_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/")
        assert get_updated_response.status_code == status.HTTP_200_OK, get_updated_response

        assert len(get_updated_response.json()["results"]) == global_seed_count + 1
        assert_template_equals(
            get_template_from_response(get_updated_response, dashboard_template.id),
            variable_template,
        )

    def test_non_staff_user_cannot_create_dashboard(self) -> None:
        n0 = DashboardTemplate.objects.count()
        self.user.is_staff = False
        self.user.save()

        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN, response

        assert DashboardTemplate.objects.count() == n0

    def test_get_dashboard_template_by_id(self) -> None:
        n0 = DashboardTemplate.objects.count()
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert DashboardTemplate.objects.count() == n0 + 1

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}")

        assert response.status_code == status.HTTP_200_OK, response

        assert_template_equals(
            response.json(),
            variable_template,
        )

    def test_delete_dashboard_template_by_id(self) -> None:
        n0 = DashboardTemplate.objects.count()
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert DashboardTemplate.objects.count() == n0 + 1
        dashboard_template = DashboardTemplate.objects.get(id=response.json()["id"])

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"deleted": True},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response

        get_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_response.status_code == status.HTTP_200_OK, get_response

        assert get_template_from_response(get_response, dashboard_template.id) is None
        assert (
            len(get_response.json()["results"])
            == DashboardTemplate.objects.filter(scope=DashboardTemplate.Scope.GLOBAL).count()
        )

    def test_soft_deleted_dashboard_template_can_be_restored_via_patch(self) -> None:
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        template_id = response.json()["id"]

        assert (
            self.client.patch(
                f"/api/projects/{self.team.pk}/dashboard_templates/{template_id}",
                {"deleted": True},
            ).status_code
            == status.HTTP_200_OK
        )

        restore = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{template_id}",
            {"deleted": False},
        )
        assert restore.status_code == status.HTTP_200_OK, restore.content
        assert restore.json()["deleted"] in (False, None)

        list_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert list_response.status_code == status.HTTP_200_OK
        assert get_template_from_response(list_response, template_id) is not None

    def test_non_staff_user_cannot_delete_dashboard_template_by_id(self) -> None:
        n0 = DashboardTemplate.objects.count()
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED, response
        assert DashboardTemplate.objects.count() == n0 + 1

        self.user.is_staff = False
        self.user.save()

        patch_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"deleted": True},
        )
        assert patch_response.status_code == status.HTTP_403_FORBIDDEN, patch_response

        get_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")
        assert get_response.status_code == status.HTTP_200_OK, get_response

        assert len(get_response.json()["results"]) == _listable_dashboard_template_db_count(self.team.pk)

    def test_update_dashboard_template_by_id(self) -> None:
        n0 = DashboardTemplate.objects.count()
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            variable_template,
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert DashboardTemplate.objects.count() == n0 + 1

        update_response = self.client.patch(
            f"/api/projects/{self.team.pk}/dashboard_templates/{response.json()['id']}",
            {"template_name": "new name"},
        )
        assert update_response.status_code == status.HTTP_200_OK, update_response
        assert update_response.json()["template_name"] == "new name"

    def test_dashboard_template_schema(self) -> None:
        dashboard_template_schema = {
            "type": "object",
            "required": [
                "template_name",
                "dashboard_description",
                "dashboard_filters",
                "tiles",
            ],
            "properties": {
                "id": {
                    "description": "The id of the dashboard template",
                    "type": "string",
                },
                "template_name": {
                    "description": "The name of the dashboard template",
                    "type": "string",
                },
                "team_id": {
                    "description": "The team this dashboard template belongs to",
                    "type": ["number", "null"],
                },
                "created_at": {
                    "description": "When the dashboard template was created",
                    "type": "string",
                },
                "image_url": {
                    "description": "The image of the dashboard template",
                    "type": ["string", "null"],
                },
                "dashboard_description": {
                    "description": "The description of the dashboard template",
                    "type": "string",
                },
                "dashboard_filters": {
                    "description": "The filters of the dashboard template",
                    "type": "object",
                },
                "tiles": {
                    "description": "The tiles of the dashboard template",
                    "type": "array",
                    "items": {"type": "object"},
                    "minItems": 1,
                },
                "variables": {
                    "description": "The variables of the dashboard template",
                    "anyOf": [
                        {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": [
                                    "id",
                                    "name",
                                    "type",
                                    "default",
                                    "description",
                                    "required",
                                ],
                                "properties": {
                                    "id": {
                                        "description": "The id of the variable",
                                        "type": "string",
                                    },
                                    "name": {
                                        "description": "The name of the variable",
                                        "type": "string",
                                    },
                                    "type": {
                                        "description": "The type of the variable",
                                        "enum": ["event"],
                                    },
                                    "default": {
                                        "description": "The default value of the variable",
                                        "type": "object",
                                    },
                                    "description": {
                                        "description": "The description of the variable",
                                        "type": "string",
                                    },
                                    "required": {
                                        "description": "Whether the variable is required",
                                        "type": "boolean",
                                    },
                                },
                            },
                        },
                        {"type": "null"},
                    ],
                },
                "tags": {
                    "description": "The tags of the dashboard template",
                    "type": "array",
                    "items": {"type": "string"},
                },
                "is_featured": {
                    "description": "Whether this template is manually marked as featured in the UI",
                    "type": "boolean",
                },
            },
        }

        response = self.client.get(
            f"/api/projects/{self.team.pk}/dashboard_templates/json_schema",
        )
        assert response.status_code == status.HTTP_200_OK

        assert response.json() == dashboard_template_schema
        assert response.headers["Cache-Control"] == "max-age=120"

    @parameterized.expand(
        [
            ("template_name", ["Alpha", "Zebra"]),
            ("-template_name", ["Zebra", "Alpha"]),
        ]
    )
    def test_ordering_when_listing_templates_without_search(self, ordering: str, expected_names: list[str]) -> None:
        DashboardTemplate.objects.all().delete()

        self.create_template({"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "Zebra"})
        self.create_template({"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "Alpha"})

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?ordering={ordering}")
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 2
        assert [r["template_name"] for r in results] == expected_names

    def test_ordering_by_created_at_when_listing_templates_without_search(self) -> None:
        DashboardTemplate.objects.all().delete()

        older_id = self.create_template(
            {"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "Older", "is_featured": False}
        )
        newer_id = self.create_template(
            {"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "Newer", "is_featured": False}
        )
        DashboardTemplate.objects.filter(id=older_id).update(created_at=datetime(2020, 6, 1, 12, 0, 0, tzinfo=UTC))
        DashboardTemplate.objects.filter(id=newer_id).update(created_at=datetime(2021, 6, 1, 12, 0, 0, tzinfo=UTC))

        asc_resp = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?ordering=created_at")
        assert asc_resp.status_code == status.HTTP_200_OK
        assert [r["template_name"] for r in asc_resp.json()["results"]] == ["Older", "Newer"]

        desc_resp = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?ordering=-created_at")
        assert desc_resp.status_code == status.HTTP_200_OK
        assert [r["template_name"] for r in desc_resp.json()["results"]] == ["Newer", "Older"]

    def test_default_ordering_when_listing_templates(self) -> None:
        DashboardTemplate.objects.all().delete()

        self.create_template({"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "Zebra"})
        self.create_template({"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "Alpha"})

        default_order = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/")
        assert default_order.status_code == status.HTTP_200_OK
        default_results = default_order.json()["results"]
        assert len(default_results) == 2
        assert [r["template_name"] for r in default_results] == ["Alpha", "Zebra"]

    def test_featured_templates_list_before_non_featured_when_listing_without_search(self) -> None:
        DashboardTemplate.objects.all().delete()
        self.create_template(
            {
                "scope": DashboardTemplate.Scope.GLOBAL,
                "template_name": "Aardvark not featured",
                "is_featured": False,
            }
        )
        self.create_template(
            {
                "scope": DashboardTemplate.Scope.GLOBAL,
                "template_name": "Zebra featured",
                "is_featured": True,
            }
        )

        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/")
        assert response.status_code == status.HTTP_200_OK
        assert [r["template_name"] for r in response.json()["results"]] == ["Zebra featured", "Aardvark not featured"]

    def test_search_when_listing_templates(self):
        # ensure there are no templates
        DashboardTemplate.objects.all().delete()

        self.create_template({"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "pony template"})
        self.create_template(
            {
                "scope": DashboardTemplate.Scope.GLOBAL,
                "template_name": "wat template",
                "dashboard_description": "description with pony",
            }
        )
        self.create_template(
            {"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "tagged wat template", "tags": ["pony", "horse"]}
        )
        self.create_template(
            {
                "scope": DashboardTemplate.Scope.GLOBAL,
                "template_name": "tagged ponies template",
                "tags": ["goat", "horse"],
            }
        )
        not_pony_template_id = self.create_template(
            {"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "goat template"}
        )

        default_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/")
        assert default_response.status_code == status.HTTP_200_OK
        assert len(default_response.json()["results"]) == 5

        # will match pony and ponies
        pony_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?search=pony")
        assert pony_response.status_code == status.HTTP_200_OK
        assert len(pony_response.json()["results"]) == 4
        assert not_pony_template_id not in [r["id"] for r in pony_response.json()["results"]]

    def test_filter_template_list_by_scope(self):
        # ensure there are no templates
        DashboardTemplate.objects.all().delete()

        # create a flag and a global scoped template
        flag_template_id = self.create_template(
            {"scope": DashboardTemplate.Scope.FEATURE_FLAG, "template_name": "flag scoped template"}
        )
        global_template_id = self.create_template(
            {"scope": DashboardTemplate.Scope.GLOBAL, "template_name": "globally scoped template"}
        )
        team_template_id = self.create_template(
            {"scope": DashboardTemplate.Scope.ONLY_TEAM, "template_name": "team scoped template"}
        )

        default_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/")
        assert default_response.status_code == status.HTTP_200_OK
        default_rows = default_response.json()["results"]
        assert len(default_rows) == 3
        assert {(r["id"], r["scope"]) for r in default_rows} == {
            (flag_template_id, "feature_flag"),
            (global_template_id, "global"),
            (team_template_id, "team"),
        }

        team_only_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?scope=team")
        assert team_only_response.status_code == status.HTTP_200_OK
        assert [(r["id"], r["scope"]) for r in team_only_response.json()["results"]] == [(team_template_id, "team")]

        global_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?scope=global")
        assert global_response.status_code == status.HTTP_200_OK
        assert [(r["id"], r["scope"]) for r in global_response.json()["results"]] == [(global_template_id, "global")]

        flag_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?scope=feature_flag")
        assert flag_response.status_code == status.HTTP_200_OK
        assert [(r["id"], r["scope"]) for r in flag_response.json()["results"]] == [(flag_template_id, "feature_flag")]

    def test_filter_template_list_by_is_featured(self) -> None:
        DashboardTemplate.objects.all().delete()
        featured_id = self.create_template(
            {"template_name": "Featured list filter A", "is_featured": True},
        )
        not_featured_id = self.create_template(
            {"template_name": "Not featured list filter B", "is_featured": False},
        )

        all_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/")
        assert all_response.status_code == status.HTTP_200_OK
        all_results = all_response.json()["results"]
        assert len(all_results) == 2
        assert [r["template_name"] for r in all_results] == ["Featured list filter A", "Not featured list filter B"]

        featured_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?is_featured=true")
        assert featured_response.status_code == status.HTTP_200_OK
        featured_ids = {r["id"] for r in featured_response.json()["results"]}
        assert featured_ids == {featured_id}

        not_featured_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?is_featured=false")
        assert not_featured_response.status_code == status.HTTP_200_OK
        not_featured_ids = {r["id"] for r in not_featured_response.json()["results"]}
        assert not_featured_ids == {not_featured_id}

    def test_is_featured_list_excludes_feature_flag_scoped_templates(self) -> None:
        """`?is_featured=true` on the default list does not pull in `scope=feature_flag` rows (use `scope=feature_flag` for those)."""
        DashboardTemplate.objects.all().delete()
        team_featured = self.create_template(
            {"template_name": "Featured team scoped FF test", "is_featured": True, "scope": "team"},
        )
        global_featured = self.create_template(
            {"template_name": "Featured global scoped FF test", "is_featured": True, "scope": "global"},
        )
        flag_featured = self.create_template(
            {
                "template_name": "Featured feature_flag scoped FF test",
                "is_featured": True,
                "scope": DashboardTemplate.Scope.FEATURE_FLAG,
            },
        )
        response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates/?is_featured=true")
        assert response.status_code == status.HTTP_200_OK
        ids = {r["id"] for r in response.json()["results"]}
        assert ids == {team_featured, global_featured}
        assert flag_featured not in ids

    def create_template(self, overrides: dict[str, Any], team_id: Optional[int] = None) -> str:
        template = {**variable_template, **overrides}
        response = self.client.post(
            f"/api/projects/{team_id or self.team.pk}/dashboard_templates",
            template,
        )
        assert response.status_code == status.HTTP_201_CREATED
        id = response.json()["id"]

        return id

    def test_cannot_escape_team_when_filtering_template_list(self):
        # create another team, and log in as a user from that team
        another_team = Team.objects.create(name="Another Team", organization=self.organization)
        another_team_user = User.objects.create_and_join(
            organization=self.organization, first_name="Another", email="another_user@email.com", password="wat"
        )
        another_team_user.current_team = another_team
        another_team_user.is_staff = True
        another_team_user.save()

        self.client.force_login(another_team_user)

        # create a dashboard template in that other team
        id = self.create_template(
            {"scope": DashboardTemplate.Scope.ONLY_TEAM, "template_name": "other teams template"},
            team_id=another_team.pk,
        )

        # the user from another_team can access the new dashboard via the API on their own team
        list_response = self.client.get(f"/api/projects/{another_team.pk}/dashboard_templates/")
        assert list_response.status_code == status.HTTP_200_OK
        assert id in [r["id"] for r in list_response.json()["results"]]

        # the user from the home team cannot see the dashboard by default
        self.client.force_login(self.user)
        home_list_response = self.client.get(f"/api/projects/{self.team.pk}/dashboard_templates")

        assert home_list_response.status_code == status.HTTP_200_OK
        assert id not in [r["id"] for r in home_list_response.json()["results"]]

        # the user form the home team cannot escape their permissions by passing filters
        attempted_escape_response = self.client.get(
            f"/api/projects/{self.team.pk}/dashboard_templates/?team_id={another_team.pk}"
        )
        assert attempted_escape_response.status_code == status.HTTP_200_OK
        assert id not in [r["id"] for r in attempted_escape_response.json()["results"]]

        # searching by text doesn't get around the team filtering
        another_attempted_escape_response = self.client.get(
            f"/api/projects/{self.team.pk}/dashboard_templates/?search=other"
        )
        assert another_attempted_escape_response.status_code == status.HTTP_200_OK
        assert id not in [r["id"] for r in another_attempted_escape_response.json()["results"]]


@contextmanager
def _customer_dashboard_template_authoring_flag_on():
    with patch(
        "products.dashboards.backend.api.dashboard_templates.posthoganalytics.feature_enabled",
        return_value=True,
    ):
        yield


class TestCustomerDashboardTemplateAuthoring(APIBaseTest):
    """Phase 1 customer authoring: org flag + editor on `dashboard_template` (not flag alone)."""

    def setUp(self):
        super().setUp()
        self.user.is_staff = False
        self.user.save()
        ensure_baseline_global_dashboard_templates()
        self.organization.available_product_features = [
            {"name": AvailableFeature.ADVANCED_PERMISSIONS, "key": AvailableFeature.ADVANCED_PERMISSIONS},
        ]
        self.organization.save()

    def _grant_template_viewer(self) -> None:
        # `dashboard_template` inherits access from `dashboard`, so viewer on the parent resource
        # is what limits a non-staff user to read-only template access.
        AccessControl.objects.create(
            team=self.team,
            resource="dashboard",
            resource_id=None,
            organization_member=self.organization_membership,
            role=None,
            access_level="viewer",
        )

    def test_non_staff_flag_off_unsafe_forbidden(self) -> None:
        response = self.client.post(f"/api/projects/{self.team.pk}/dashboard_templates", variable_template)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_staff_flag_on_viewer_forbidden(self) -> None:
        self._grant_template_viewer()
        with _customer_dashboard_template_authoring_flag_on():
            response = self.client.post(f"/api/projects/{self.team.pk}/dashboard_templates", variable_template)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_non_staff_flag_on_editor_post_patch_delete_team_template(self) -> None:
        with _customer_dashboard_template_authoring_flag_on():
            create = self.client.post(f"/api/projects/{self.team.pk}/dashboard_templates", variable_template)
        assert create.status_code == status.HTTP_201_CREATED, create
        tid = create.json()["id"]

        with _customer_dashboard_template_authoring_flag_on():
            patch_resp = self.client.patch(
                f"/api/projects/{self.team.pk}/dashboard_templates/{tid}",
                {"template_name": "Renamed", "tags": ["a"]},
            )
        assert patch_resp.status_code == status.HTTP_200_OK, patch_resp
        assert patch_resp.json()["template_name"] == "Renamed"

        with _customer_dashboard_template_authoring_flag_on():
            del_resp = self.client.patch(
                f"/api/projects/{self.team.pk}/dashboard_templates/{tid}",
                {"deleted": True},
            )
        assert del_resp.status_code == status.HTTP_200_OK, del_resp

    def test_non_staff_patch_with_tiles_returns_400(self) -> None:
        self.user.is_staff = True
        self.user.save()
        create = self.client.post(f"/api/projects/{self.team.pk}/dashboard_templates", variable_template)
        tid = create.json()["id"]
        self.user.is_staff = False
        self.user.save()

        with _customer_dashboard_template_authoring_flag_on():
            bad = self.client.patch(
                f"/api/projects/{self.team.pk}/dashboard_templates/{tid}",
                {"template_name": "x", "tiles": variable_template["tiles"]},
            )
        assert bad.status_code == status.HTTP_400_BAD_REQUEST
        assert bad.json().get("attr") == "tiles"

    @parameterized.expand(
        [
            ("scope", "global"),
            ("is_featured", True),
        ]
    )
    def test_non_staff_post_staff_only_fields_400(self, field: str, value: Any) -> None:
        body = {**variable_template, field: value}
        with _customer_dashboard_template_authoring_flag_on():
            response = self.client.post(f"/api/projects/{self.team.pk}/dashboard_templates", body)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json().get("attr") == field

    def test_non_staff_cannot_patch_global_or_feature_flag_template(self) -> None:
        global_tpl = DashboardTemplate.objects.filter(scope=DashboardTemplate.Scope.GLOBAL).first()
        assert global_tpl is not None

        ff_tpl = DashboardTemplate.objects.create(
            team_id=self.team.pk,
            scope=DashboardTemplate.Scope.FEATURE_FLAG,
            template_name="ff tpl",
            dashboard_description="",
            dashboard_filters={},
            tiles=variable_template["tiles"],
            variables=[],
            tags=[],
        )

        with _customer_dashboard_template_authoring_flag_on():
            r1 = self.client.patch(
                f"/api/projects/{self.team.pk}/dashboard_templates/{global_tpl.id}",
                {"template_name": "nope"},
            )
            r2 = self.client.patch(
                f"/api/projects/{self.team.pk}/dashboard_templates/{ff_tpl.id}",
                {"template_name": "nope"},
            )
        assert r1.status_code == status.HTTP_403_FORBIDDEN
        assert r2.status_code == status.HTTP_403_FORBIDDEN

    def test_non_staff_wrong_team_template_id_returns_404(self) -> None:
        other_org = Organization.objects.create(name="Other org for template idor")
        other_team = Team.objects.create(organization=other_org, name="Other team tpl")
        other_tpl = DashboardTemplate.objects.create(
            team_id=other_team.pk,
            scope=DashboardTemplate.Scope.ONLY_TEAM,
            template_name="other team only",
            dashboard_description="",
            dashboard_filters={},
            tiles=variable_template["tiles"],
            variables=[],
            tags=[],
        )

        with _customer_dashboard_template_authoring_flag_on():
            response = self.client.patch(
                f"/api/projects/{self.team.pk}/dashboard_templates/{other_tpl.id}",
                {"template_name": "hax"},
            )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_staff_unsafe_succeeds_when_flag_off(self) -> None:
        self.user.is_staff = True
        self.user.save()
        response = self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {**variable_template, "template_name": "Staff global featured", "scope": "global", "is_featured": True},
        )
        assert response.status_code == status.HTTP_201_CREATED, response

    @patch("products.dashboards.backend.api.dashboard_templates.report_user_action")
    def test_create_emits_analytics_for_non_global_scope(self, mock_report) -> None:
        self.user.is_staff = True
        self.user.save()
        self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {**variable_template, "template_name": "Analytics emit team scoped"},
        )
        mock_report.assert_called()
        call_kwargs = mock_report.call_args.kwargs
        assert call_kwargs["properties"]["scope"] == "team"
        assert call_kwargs["properties"]["tile_count"] == len(variable_template["tiles"])

        mock_report.reset_mock()
        self.client.post(
            f"/api/projects/{self.team.pk}/dashboard_templates",
            {**variable_template, "template_name": "Analytics emit global scoped", "scope": "global"},
        )
        mock_report.assert_not_called()

import json
from collections.abc import Sequence

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.actions.backend.models.action import Action as EventAction
from products.authz.backend.facade.contracts import CheckRequest, Context, Resource, ResourceIds
from products.authz.backend.facade.enums import Action, ResourceType
from products.cohorts.backend.models.cohort import Cohort
from products.dashboards.backend.facade import testing as dashboard_testing
from products.dashboards.backend.models.dashboard import Dashboard
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight

SAVED_DASHBOARD_FILTERS = {
    "breakdown_filter": {"breakdown": "email", "breakdown_type": "person"},
    "properties": [{"type": "hogql", "key": "person.properties.email = 'a'"}],
}


class TestGuestObjectAccess(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"key": AvailableFeature.ADVANCED_PERMISSIONS, "name": "Advanced permissions"}
        ]
        self.organization.save()
        self.organization_membership.level = OrganizationMembership.Level.GUEST
        self.organization_membership.save()
        # A guest invite always creates this project rule, which admits the guest to the project.
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            organization_member=self.organization_membership,
            access_level="member",
        )
        self.granted = Notebook.objects.create(team=self.team, title="Granted")
        self.hidden = Notebook.objects.create(team=self.team, title="Hidden")
        self.dashboard_id = dashboard_testing.create_dashboard(team_id=self.team.id)
        self.cohort = Cohort.objects.create(team=self.team, name="Used")
        self.unused_cohort = Cohort.objects.create(team=self.team, name="Unused")
        self.action = EventAction.objects.create(team=self.team, name="Used")
        self.unused_action = EventAction.objects.create(team=self.team, name="Unused")
        self.insight = Insight.objects.create(
            team=self.team,
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [
                        {"kind": "ActionsNode", "id": self.action.id},
                        {
                            "kind": "EventsNode",
                            "properties": [{"type": "cohort", "key": "id", "value": self.cohort.id}],
                        },
                    ],
                },
            },
        )
        for target, kwargs in (
            ("products.authz.backend.logic.rollout.get_feature_flag_or_none", {"return_value": "v2"}),
            ("products.authz.backend.logic.authorization.check", {"side_effect": self._openfga_check}),
            ("products.authz.backend.logic.authorization.list_resources", {"side_effect": self._openfga_list}),
        ):
            patcher = patch(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _openfga_list(self, resource: Resource, *_args: object) -> ResourceIds:
        granted = {ResourceType.NOTEBOOK: str(self.granted.id), ResourceType.INSIGHT: str(self.insight.id)}
        if resource.type not in granted:
            raise ValueError("List resources requires a supported resource type")
        return ResourceIds(ids=frozenset({granted[resource.type]}), complete=True)

    def _openfga_check(self, requests: Sequence[CheckRequest], _context: Context | None) -> list[bool]:
        granted = {
            (ResourceType.NOTEBOOK, str(self.granted.id)),
            (ResourceType.DASHBOARD, str(self.dashboard_id)),
            (ResourceType.INSIGHT, str(self.insight.id)),
        }
        return [
            request.resource.type in (ResourceType.PROJECT, ResourceType.ORGANIZATION)
            or (request.action == Action.VIEW and (request.resource.type, request.resource.id) in granted)
            for request in requests
        ]

    def test_guest_lists_only_granted_notebooks(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/notebooks/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert [item["short_id"] for item in response.json()["results"]] == [self.granted.short_id]

    def test_guest_reads_a_granted_notebook_and_not_another(self) -> None:
        granted = self.client.get(f"/api/projects/{self.team.id}/notebooks/{self.granted.short_id}/")
        hidden = self.client.get(f"/api/projects/{self.team.id}/notebooks/{self.hidden.short_id}/")
        assert granted.status_code == status.HTTP_200_OK, granted.json()
        assert hidden.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND), hidden.json()

    @parameterized.expand([("notebooks", "granted", "short_id"), ("insights", "insight", "id")])
    def test_guest_loses_a_granted_object_once_it_is_deleted(self, path: str, attribute: str, key: str) -> None:
        granted = getattr(self, attribute)
        granted.deleted = True
        granted.save()
        listed = self.client.get(f"/api/projects/{self.team.id}/{path}/")
        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert listed.json()["results"] == []
        retrieved = self.client.get(f"/api/projects/{self.team.id}/{path}/{getattr(granted, key)}/")
        assert retrieved.status_code == status.HTTP_404_NOT_FOUND, retrieved.json()

    @parameterized.expand([("retrieve", ""), ("stream tiles", "stream_tiles/")])
    def test_guest_loses_a_granted_dashboard_once_it_is_deleted(self, _name: str, path: str) -> None:
        dashboard_testing.set_dashboard_deleted(team_id=self.team.id, dashboard_id=self.dashboard_id, deleted=True)
        response = self.client.get(f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/{path}")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_guest_cannot_list_recordings(self) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/session_recordings/")
        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content

    @parameterized.expand(
        [
            ("saved filters", {}, 200),
            ("new breakdown", {"breakdown_filter": {"breakdown": "name", "breakdown_type": "person"}}, 403),
            (
                "new hogql filter",
                {"properties": [*SAVED_DASHBOARD_FILTERS["properties"], {"type": "hogql", "key": "1 = 1"}]},
                403,
            ),
        ]
    )
    def test_guest_dashboard_overrides_may_repeat_the_saved_filters(
        self, _name: str, change: dict, expected: int
    ) -> None:
        Dashboard.objects.filter(id=self.dashboard_id).update(filters=SAVED_DASHBOARD_FILTERS)
        override = {**SAVED_DASHBOARD_FILTERS, "date_from": "-7d", **change}
        response = self.client.get(
            f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/", {"filters_override": json.dumps(override)}
        )
        assert response.status_code == expected, response.json()

    def test_guest_cannot_edit_a_granted_dashboard(self) -> None:
        url = f"/api/projects/{self.team.id}/dashboards/{self.dashboard_id}/"
        assert self.client.get(url).status_code == status.HTTP_200_OK
        assert self.client.patch(url, {"name": "Changed"}).status_code == status.HTTP_403_FORBIDDEN

    @parameterized.expand([("cohorts", "cohort"), ("actions", "action")])
    def test_guest_reads_only_the_cohorts_and_actions_their_insights_use(self, path: str, attribute: str) -> None:
        used, unused = getattr(self, attribute), getattr(self, f"unused_{attribute}")
        listed = self.client.get(f"/api/projects/{self.team.id}/{path}/")
        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert [item["id"] for item in listed.json()["results"]] == [used.id]
        assert self.client.get(f"/api/projects/{self.team.id}/{path}/{used.id}/").status_code == status.HTTP_200_OK
        assert (
            self.client.get(f"/api/projects/{self.team.id}/{path}/{unused.id}/").status_code
            == status.HTTP_404_NOT_FOUND
        )

    @parameterized.expand(
        [
            ("breakdown", {"breakdown_filter": {"breakdown": "email", "breakdown_type": "person"}}, 403),
            ("hogql filter", {"properties": [{"type": "hogql", "key": "person.properties.email = 'a'"}]}, 403),
            ("date range", {"date_from": "-7d"}, 200),
        ]
    )
    def test_guest_insight_overrides_cannot_expose_values(self, _name: str, override: dict, expected: int) -> None:
        response = self.client.get(
            f"/api/projects/{self.team.id}/insights/{self.insight.id}/", {"filters_override": json.dumps(override)}
        )
        assert response.status_code == expected, response.json()

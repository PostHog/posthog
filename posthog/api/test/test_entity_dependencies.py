from typing import Any

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import EntityDependency, Organization, Team

from products.cohorts.backend.models.cohort import Cohort
from products.workflows.backend.models.hog_flow.hog_flow import HogFlow


def _batch_trigger(cohort_id: Any) -> dict[str, Any]:
    return {
        "type": "trigger",
        "config": {
            "type": "batch",
            "filters": {"properties": [{"key": "id", "type": "cohort", "value": cohort_id, "operator": "in"}]},
        },
    }


class TestEntityDependenciesAPI(APIBaseTest):
    def _get(self, params: dict[str, Any]) -> Any:
        return self.client.get(f"/api/projects/{self.team.id}/dependencies/", params)

    def test_lists_workflows_referencing_a_cohort(self) -> None:
        cohort = Cohort.objects.create(team=self.team, name="Trial users")
        flow = HogFlow.objects.create(team=self.team, name="Trial nurture", trigger=_batch_trigger(cohort.pk))

        response = self._get({"target_type": "cohort", "target_id": str(cohort.pk)})

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == [
            {
                "type": "hog_flow",
                "total": 1,
                "has_more": False,
                "results": [
                    {
                        "entity": {
                            "type": "hog_flow",
                            "id": str(flow.id),
                            "name": "Trial nurture",
                            "url": f"/workflows/{flow.id}/workflow",
                            "status": "active",
                        },
                        "roles": ["trigger_audience"],
                    }
                ],
            }
        ]

    def test_lists_what_a_workflow_references_with_per_target_statuses(self) -> None:
        active = Cohort.objects.create(team=self.team, name="Active")
        deleted = Cohort.objects.create(team=self.team, name="Gone", deleted=True)
        dangling_id = "999999"
        flow = HogFlow.objects.create(
            team=self.team,
            name="Flow",
            trigger=_batch_trigger(active.pk),
            conversion={
                "filters": [
                    {"key": "id", "type": "cohort", "value": deleted.pk, "operator": "in"},
                    {"key": "id", "type": "cohort", "value": dangling_id, "operator": "in"},
                ],
                "events": [],
            },
        )
        EntityDependency(
            team=self.team, source_type="hog_flow", source_id=str(flow.id), target_type="insight", target_id="42"
        ).save()

        response = self._get({"source_type": "hog_flow", "source_id": str(flow.id)})

        assert response.status_code == status.HTTP_200_OK
        groups = response.json()
        assert [group["type"] for group in groups] == ["cohort", "insight"]
        statuses = {entry["entity"]["id"]: entry["entity"]["status"] for entry in groups[0]["results"]}
        assert statuses == {str(active.pk): "active", str(deleted.pk): "deleted", dangling_id: "missing"}
        assert groups[1]["results"][0]["entity"] == {
            "type": "insight",
            "id": "42",
            "name": "",
            "url": "",
            "status": "unknown",
        }

    def test_rows_of_another_team_are_not_visible(self) -> None:
        other_org = Organization.objects.create(name="other")
        other_team = Team.objects.create(organization=other_org)
        cohort = Cohort.objects.create(team=other_team, name="Their cohort")
        HogFlow.objects.create(team=other_team, name="Their flow", trigger=_batch_trigger(cohort.pk))

        response = self._get({"target_type": "cohort", "target_id": str(cohort.pk)})

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    @parameterized.expand(
        [
            ("no_params", {}),
            ("both_pairs", {"target_type": "cohort", "target_id": "1", "source_type": "hog_flow", "source_id": "a"}),
            ("half_target_pair", {"target_type": "cohort"}),
            ("half_source_pair", {"source_id": "a"}),
        ]
    )
    def test_rejects_invalid_query_params(self, _name: str, params: dict[str, str]) -> None:
        response = self._get(params)

        assert response.status_code == status.HTTP_400_BAD_REQUEST

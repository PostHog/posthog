from datetime import timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models.event.util import bulk_create_events

from products.access_control.backend.facade.contracts import PropertyAccessLevel
from products.access_control.backend.models.property_access_control import PropertyAccessControl
from products.event_definitions.backend.models.property_definition import PropertyDefinition

from ...logic.traces.rows import make_cluster, make_cluster_run_event
from .trace_fixtures import T0, encode_segment


class TestTraceClustersView(ClickhouseTestMixin, APIBaseTest):
    def _url(self, segment: str) -> str:
        return f"/api/projects/{self.team.id}/ai_observability/traces/{segment}/clusters/"

    def _create_cluster_run(self) -> None:
        bulk_create_events(
            [
                make_cluster_run_event(
                    uuid="00000000-0000-0000-0000-0000000c4001",
                    team=self.team,
                    timestamp=T0 + timedelta(days=1),
                    clusters=[
                        make_cluster(3, ["trace-1"], title="Billing questions", description="Users ask about invoices.")
                    ],
                )
            ]
        )

    def test_returns_the_clusters_in_camel_case(self) -> None:
        self._create_cluster_run()

        response = self.client.get(self._url(encode_segment("trace-1")), {"created_at": T0.isoformat()})

        assert response.status_code == 200
        assert response.json()["clusters"][0] | {"runAt": None} == {
            "runId": "1_trace_20260902_030000",
            "runAt": None,
            "jobId": None,
            "jobName": None,
            "clusterId": 3,
            "title": "Billing questions",
            "label": "Billing questions",
            "description": "Users ask about invoices.",
            "isOutlier": False,
        }

    @parameterized.expand(
        [
            ("an unencoded id", "trace-1", {"created_at": "2026-09-01T10:00:00Z"}),
            ("no created_at", encode_segment("trace-1"), {}),
            ("a malformed created_at", encode_segment("trace-1"), {"created_at": "yesterday"}),
            ("an out-of-range created_at", encode_segment("trace-1"), {"created_at": "9999-12-31T00:00:00Z"}),
        ]
    )
    def test_rejects_a_malformed_request(self, _name: str, segment: str, query: dict[str, str]) -> None:
        assert self.client.get(self._url(segment), query).status_code == 400

    def test_an_api_key_needs_the_clusters_scope(self) -> None:
        key = self.create_personal_api_key_with_scopes(["llm_analytics:read"])
        self.client.logout()

        response = self.client.get(
            self._url(encode_segment("trace-1")),
            {"created_at": T0.isoformat()},
            headers={"authorization": f"Bearer {key}"},
        )

        assert response.status_code == 403

    def test_masks_clusters_the_viewer_may_not_read(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.PROPERTY_ACCESS_CONTROL, "name": AvailableFeature.PROPERTY_ACCESS_CONTROL}
        ]
        self.organization.save()
        definition = PropertyDefinition.objects.create(
            team=self.team, name="$ai_clusters", property_type="String", type=PropertyDefinition.Type.EVENT
        )
        PropertyAccessControl.objects.create(
            team=self.team,
            property_definition=definition,
            organization_member=self.organization_membership,
            access_level=PropertyAccessLevel.NONE.value,
        )
        self._create_cluster_run()

        response = self.client.get(self._url(encode_segment("trace-1")), {"created_at": T0.isoformat()})

        assert (response.status_code, response.json()) == (200, {"clusters": []})

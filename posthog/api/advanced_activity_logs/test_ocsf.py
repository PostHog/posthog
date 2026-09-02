from typing import Optional

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.api.advanced_activity_logs.ocsf import ActivityLogOCSFSerializer
from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail


class TestActivityLogOCSF(APIBaseTest):
    def _log(self, activity: str = "updated", detail: Optional[Detail] = None) -> ActivityLog:
        log = ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            scope="FeatureFlag",
            activity=activity,
            item_id="flag-1",
            user=self.user,
            ip_address="203.0.113.4",
            client="posthog-python",
            detail=detail,
        )
        # Read it back so `detail` is the JSON dict the list endpoint serializes, not the dataclass
        # the freshly built instance holds.
        log.refresh_from_db()
        return log

    def _detail_with_values(self) -> Detail:
        return Detail(
            name="beta-checkout",
            changes=[Change(type="FeatureFlag", action="changed", field="filters", before={"a": 1}, after={"a": 2})],
        )

    @parameterized.expand(
        [
            ("created", 3004, 1, None),
            ("updated", 3004, 3, None),
            ("deleted", 3004, 4, None),
            ("logged_in", 3002, 1, None),
            ("scim_provisioned", 3001, 1, None),
            ("exported for opengraph image", 3004, 99, "exported for opengraph image"),
        ]
    )
    def test_activity_maps_to_class_and_activity_id(
        self, activity: str, class_uid: int, activity_id: int, activity_name: Optional[str]
    ):
        event = ActivityLogOCSFSerializer(self._log(activity=activity)).data

        assert event["class_uid"] == class_uid
        assert event["activity_id"] == activity_id
        if activity_name is None:
            assert "activity_name" not in event
        else:
            assert event["activity_name"] == activity_name

    def test_values_are_excluded_by_default_but_field_names_are_kept(self):
        event = ActivityLogOCSFSerializer(self._log(detail=self._detail_with_values())).data

        assert event["unmapped"]["changed_fields"] == ["filters"]
        assert "data" not in event["entity"]
        assert "entity_result" not in event

    def test_include_values_maps_before_and_after_onto_entity_and_entity_result(self):
        event = ActivityLogOCSFSerializer(
            self._log(detail=self._detail_with_values()), context={"include_values": True}
        ).data

        assert event["entity"]["data"] == {"filters": {"a": 1}}
        assert event["entity_result"]["data"] == {"filters": {"a": 2}}

    def test_every_required_ocsf_attribute_is_present(self):
        # A strict OCSF consumer rejects an event missing any of these.
        event = ActivityLogOCSFSerializer(self._log()).data

        for attribute in ("metadata", "time", "class_uid", "category_uid", "type_uid", "activity_id", "severity_id"):
            assert attribute in event, f"missing required OCSF attribute: {attribute}"

    def test_client_is_reported_as_the_actor_app_rather_than_unmapped(self):
        event = ActivityLogOCSFSerializer(self._log()).data

        assert event["actor"]["app_name"] == "posthog-python"
        assert "client" not in event["unmapped"]

    def test_time_is_epoch_milliseconds_and_time_dt_is_rfc3339(self):
        log = self._log()

        event = ActivityLogOCSFSerializer(log).data

        assert isinstance(event["time"], int)
        assert event["time"] == int(log.created_at.timestamp() * 1000)
        assert event["time_dt"] == log.created_at.isoformat()

    def test_actor_entity_and_source_endpoint_are_mapped(self):
        event = ActivityLogOCSFSerializer(self._log(detail=self._detail_with_values())).data

        assert event["actor"]["user"]["email_addr"] == self.user.email
        assert event["src_endpoint"]["ip"] == "203.0.113.4"
        assert event["entity"] == {"type": "FeatureFlag", "uid": "flag-1", "name": "beta-checkout"}
        assert event["metadata"]["version"] == "1.5.0"
        assert event["category_uid"] == 3

    @parameterized.expand([("save_rejected_conflict", 2), ("share_login_failed", 2), ("updated", 1)])
    def test_rejected_writes_are_reported_as_failures(self, activity: str, status_id: int):
        assert ActivityLogOCSFSerializer(self._log(activity=activity)).data["status_id"] == status_id

    def test_endpoint_returns_ocsf_when_requested(self):
        self._log()

        response = self.client.get(f"/api/projects/{self.team.id}/advanced_activity_logs/?schema=ocsf")

        assert response.status_code == 200, response.json()
        assert response.json()["results"][0]["class_uid"] == 3004

    def test_endpoint_include_values_is_opt_in(self):
        self._log(detail=self._detail_with_values())
        base = f"/api/projects/{self.team.id}/advanced_activity_logs/?schema=ocsf"

        without = self.client.get(base).json()["results"][0]
        assert "entity_result" not in without

        with_values = self.client.get(f"{base}&include_values=true").json()["results"][0]
        assert with_values["entity_result"]["data"] == {"filters": {"a": 2}}

    def test_endpoint_default_shape_is_unchanged(self):
        self._log()

        response = self.client.get(f"/api/projects/{self.team.id}/advanced_activity_logs/")

        row = response.json()["results"][0]
        assert row["activity"] == "updated"
        assert "class_uid" not in row

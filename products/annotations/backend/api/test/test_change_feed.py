from datetime import UTC, datetime, timedelta

import time_machine
from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models import User
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.access_control.backend.models.access_control import AccessControl
from products.annotations.backend.models.annotation import Annotation
from products.error_tracking.backend.facade.testing import create_release

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)


class TestChangeFeed(APIBaseTest):
    def _log_activity(
        self,
        *,
        at: datetime,
        scope: str = "FeatureFlag",
        item_id: str = "101",
        name: str = "new-checkout",
        activity: str = "updated",
        changed_fields: list[str] | None = None,
        detail_type: str | None = None,
    ) -> None:
        detail: dict = {
            "name": name,
            "changes": [
                {"type": scope, "action": "changed", "field": field, "before": None, "after": None}
                for field in changed_fields or []
            ],
        }
        if detail_type is not None:
            detail["type"] = detail_type
        ActivityLog.objects.create(
            team_id=self.team.id,
            organization_id=self.organization.id,
            user=self.user,
            scope=scope,
            item_id=item_id,
            activity=activity,
            created_at=at,
            detail=detail,
        )

    def _create_annotation(self, *, at: datetime) -> None:
        Annotation.objects.create(
            team=self.team,
            organization=self.organization,
            content="Deploy checkout service",
            date_marker=at,
            scope=Annotation.Scope.PROJECT,
        )

    def _list(self, headers: dict[str, str] | None = None, **params: str | list[str]) -> dict:
        response = self.client.get(f"/api/projects/{self.team.id}/change_feed/", params, headers=headers or {})
        assert response.status_code == 200, response.json()
        return response.json()

    @time_machine.travel(NOW, tick=False)
    def test_merges_sources_newest_first_inside_the_window(self) -> None:
        self._log_activity(at=NOW - timedelta(days=2), activity="created")
        self._log_activity(at=NOW - timedelta(hours=2), changed_fields=["active", "active"])
        self._log_activity(at=NOW - timedelta(minutes=100), scope="Experiment", item_id="7", name="Checkout test")
        self._log_activity(
            at=NOW - timedelta(minutes=90), scope="Experiment", item_id="8", name="Holdout", detail_type="holdout"
        )
        with time_machine.travel(NOW - timedelta(hours=1), tick=False):
            create_release(team_id=self.team.id, hash_id="checkout-1.4.0", version="1.4.0", project="checkout")
        self._create_annotation(at=NOW - timedelta(minutes=30))

        feed = self._list(date_from=(NOW - timedelta(hours=3)).isoformat())

        assert [(change["kind"], change["name"]) for change in feed["results"]] == [
            ("annotation", "Deploy checkout service"),
            ("release", "1.4.0"),
            ("experiment", "Checkout test"),
            ("feature_flag", "new-checkout"),
        ]
        release, flag = feed["results"][1], feed["results"][3]
        assert (release["name"], release["service"]) == ("1.4.0", "checkout")
        assert (flag["name"], flag["changed_fields"], flag["actor_name"]) == (
            "new-checkout",
            ["active"],
            self.user.email,
        )
        assert feed["has_more"] is False

        truncated = self._list(date_from=(NOW - timedelta(hours=3)).isoformat(), limit="2")
        assert [change["kind"] for change in truncated["results"]] == ["annotation", "release"]
        assert truncated["has_more"] is True

    @time_machine.travel(NOW, tick=False)
    def test_leaves_out_changes_to_resources_the_user_cannot_view(self) -> None:
        self.organization.available_product_features = [{"key": "access_control", "name": "Access control"}]
        self.organization.save()
        member = User.objects.create_and_join(self.organization, "change-feed-member@example.com", "password")
        AccessControl.objects.create(resource="feature_flag", team=self.team, access_level="none")
        self._log_activity(at=NOW - timedelta(hours=1), changed_fields=["filters"])
        self._create_annotation(at=NOW - timedelta(minutes=30))
        self.client.force_login(member)

        feed = self._list()

        assert [change["kind"] for change in feed["results"]] == ["annotation"]

    @parameterized.expand(
        [
            ("annotation_scope_only", ["annotation:read"], ["annotation"]),
            ("flag_scope_too", ["annotation:read", "feature_flag:read"], ["annotation", "feature_flag"]),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_api_key_sees_only_sources_its_scopes_cover(
        self, _name: str, scopes: list[str], expected_kinds: list[str]
    ) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="k", user=self.user, secure_value=hash_key_value(token), scopes=scopes)
        self.client.logout()
        self._log_activity(at=NOW - timedelta(hours=1), changed_fields=["filters"])
        self._create_annotation(at=NOW - timedelta(minutes=30))

        feed = self._list(headers={"Authorization": f"Bearer {token}"})

        assert [change["kind"] for change in feed["results"]] == expected_kinds

    @parameterized.expand(
        [
            ("repeated_keys", ["feature_flag", "experiment"]),
            ("json_encoded_array", '["feature_flag", "experiment"]'),
            ("comma_separated", "feature_flag,experiment"),
        ]
    )
    @time_machine.travel(NOW, tick=False)
    def test_kinds_returns_only_those_kinds(self, _name: str, kinds: list[str] | str) -> None:
        self._log_activity(at=NOW - timedelta(hours=2))
        self._log_activity(at=NOW - timedelta(minutes=100), scope="Experiment", item_id="7", name="Checkout test")
        with time_machine.travel(NOW - timedelta(hours=1), tick=False):
            create_release(team_id=self.team.id, hash_id="checkout-1.4.0", version="1.4.0", project="checkout")
        self._create_annotation(at=NOW - timedelta(minutes=30))

        feed = self._list(kinds=kinds)

        assert [change["kind"] for change in feed["results"]] == ["experiment", "feature_flag"]

    @parameterized.expand(
        [
            (
                "window_ends_before_it_starts",
                {"date_from": NOW.isoformat(), "date_to": (NOW - timedelta(hours=1)).isoformat()},
            ),
            ("unknown_kind", {"kinds": "deploy"}),
        ]
    )
    def test_rejects_invalid_query(self, _name: str, params: dict[str, str]) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/change_feed/", params)

        assert response.status_code == 400

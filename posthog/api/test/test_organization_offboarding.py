from datetime import timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Organization, OrganizationMembership, SessionRecording, SharingConfiguration, Team, User
from posthog.models.activity_logging.activity_log import ActivityLog

from products.access_control.backend.models.access_control import AccessControl
from products.alerts.backend.models.alert import AlertConfiguration
from products.dashboards.backend.models.dashboard import Dashboard
from products.notebooks.backend.models import Notebook
from products.product_analytics.backend.facade.models import Insight
from products.subscriptions.backend.models.subscription import Subscription


class TestOrganizationOffboarding(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self.departing = User.objects.create_and_join(self.organization, "departing@example.com", None)
        self.url = f"/api/organizations/@current/members/{self.departing.uuid}/"

    def test_review_uses_publisher_with_creator_fallback_only_when_unknown(self) -> None:
        second_team = Team.objects.create(organization=self.organization, name="Second project")
        owned = Dashboard.objects.create(team=second_team, created_by=self.departing, name="Product overview")
        shared = Dashboard.objects.create(team=self.team, created_by=self.user, name="Weekly acquisition")
        for dashboard in (owned, shared):
            SharingConfiguration.objects.create(
                team=dashboard.team,
                dashboard=dashboard,
                enabled=True,
                password_required=dashboard == owned,
                shared_by=self.departing if dashboard == shared else None,
            )
        reshared = Dashboard.objects.create(team=self.team, created_by=self.departing)
        SharingConfiguration.objects.create(team=self.team, dashboard=reshared, enabled=True, shared_by=self.user)
        history_only = Dashboard.objects.create(team=self.team, created_by=self.user)
        SharingConfiguration.objects.create(team=self.team, dashboard=history_only, enabled=True)
        ActivityLog.objects.create(
            team_id=self.team.pk,
            user=self.departing,
            scope="Dashboard",
            activity="sharing enabled",
            item_id=str(history_only.pk),
        )
        inactive = Dashboard.objects.create(team=self.team, created_by=self.departing)
        SharingConfiguration.objects.create(team=self.team, dashboard=inactive, enabled=False)
        expired = Dashboard.objects.create(team=self.team, created_by=self.departing)
        SharingConfiguration.objects.create(
            team=self.team, dashboard=expired, enabled=True, expires_at=timezone.now() - timedelta(seconds=1)
        )
        response = self.client.get(self.url + "offboarding/")
        assert response.status_code == 200
        assert {(item["name"], item["team_id"]) for item in response.json()} == {
            ("Product overview", second_team.pk),
            ("Weekly acquisition", self.team.pk),
        }
        assert all("token" not in str(item) for item in response.json())
        assert {item["name"]: item["password_required"] for item in response.json()} == {
            "Product overview": True,
            "Weekly acquisition": False,
        }
        assert {item["url"] for item in response.json()} == {
            f"/project/{second_team.pk}/dashboard/{owned.pk}",
            f"/project/{self.team.pk}/dashboard/{shared.pk}",
        }

    @parameterized.expand([("delete",), ("post",)])
    def test_removal_disables_all_dashboard_tokens_and_preserves_other_members_links(self, method: str) -> None:
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.departing, is_shared=True)
        shares = [SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)]
        shares.append(
            SharingConfiguration.objects.create(
                team=self.team, dashboard=dashboard, enabled=True, expires_at=timezone.now() + timedelta(minutes=5)
            )
        )
        other = Dashboard.objects.create(team=self.team, created_by=self.user)
        other_share = SharingConfiguration.objects.create(team=self.team, dashboard=other, enabled=True)
        response = (
            self.client.delete(self.url)
            if method == "delete"
            else self.client.post(self.url + "offboard/", {}, format="json")
        )
        assert response.status_code == 204
        assert not OrganizationMembership.objects.filter(user=self.departing, organization=self.organization).exists()
        for share in shares:
            share.refresh_from_db()
            assert not share.enabled
        dashboard.refresh_from_db()
        other_share.refresh_from_db()
        assert not dashboard.is_shared
        assert other_share.enabled

    def test_admin_can_disable_selected_dashboards(self) -> None:
        kept = Dashboard.objects.create(team=self.team, created_by=self.departing)
        disabled = Dashboard.objects.create(team=self.team, created_by=self.departing)
        kept_share = SharingConfiguration.objects.create(team=self.team, dashboard=kept, enabled=True)
        disabled_share = SharingConfiguration.objects.create(team=self.team, dashboard=disabled, enabled=True)
        response = self.client.post(
            self.url + "offboard/", {"keep": [f"public_link:dashboard:{self.team.pk}:{kept.pk}"]}, format="json"
        )
        assert response.status_code == 204
        kept_share.refresh_from_db()
        disabled_share.refresh_from_db()
        assert kept_share.enabled
        assert not disabled_share.enabled

    def test_review_and_cleanup_are_scoped_to_organization(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        dashboard = Dashboard.objects.create(team=other_team, created_by=self.departing)
        share = SharingConfiguration.objects.create(team=other_team, dashboard=dashboard, enabled=True)
        assert self.client.get(self.url + "offboarding/").json() == []
        response = self.client.post(
            self.url + "offboard/", {"keep": [f"public_link:dashboard:{other_team.pk}:{dashboard.pk}"]}, format="json"
        )
        assert response.status_code == 400
        assert OrganizationMembership.objects.filter(user=self.departing, organization=self.organization).exists()
        assert self.client.delete(self.url).status_code == 204
        share.refresh_from_db()
        assert share.enabled

    def test_member_cannot_review_or_remove_another_member(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        assert self.client.get(self.url + "offboarding/").status_code == 403
        assert self.client.post(self.url + "offboard/", {}, format="json").status_code == 403

    def test_self_removal_cannot_keep_public_links(self) -> None:
        dashboard = Dashboard.objects.create(team=self.team, created_by=self.user)
        share = SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)
        url = f"/api/organizations/@current/members/{self.user.uuid}/offboard/"
        assert (
            self.client.post(
                url, {"keep": [f"public_link:dashboard:{self.team.pk}:{dashboard.pk}"]}, format="json"
            ).status_code
            == 403
        )
        assert self.client.post(url, {}, format="json").status_code == 204
        share.refresh_from_db()
        assert not share.enabled

    @parameterized.expand([("dashboard",), ("insight",), ("notebook",)])
    @patch("posthog.api.sharing.export_asset_for_opengraph")
    def test_publishers_survive_rotation_without_activity_history(self, kind: str, _export: object) -> None:
        models: dict[str, type[Dashboard] | type[Insight] | type[Notebook]] = {
            "dashboard": Dashboard,
            "insight": Insight,
            "notebook": Notebook,
        }
        resource = models[kind].objects.create(team=self.team, created_by=self.user)
        lookup_id = resource.short_id if isinstance(resource, Notebook) else resource.pk
        route = "notebooks" if kind == "notebook" else f"{kind}s"
        self.client.force_login(self.departing)
        response = self.client.patch(
            f"/api/projects/{self.team.pk}/{route}/{lookup_id}/sharing/", {"enabled": True}, format="json"
        )
        assert response.status_code == 200
        share = SharingConfiguration.objects.get(team=self.team, **{kind: resource})
        assert share.shared_by_id == self.departing.pk
        rotated = share.rotate_access_token()
        assert rotated.shared_by_id == self.departing.pk
        ActivityLog.objects.filter(team_id=self.team.pk, user=self.departing).delete()
        self.client.force_login(self.user)
        response = self.client.get(self.url + "offboarding/")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [f"public_link:{kind}:{self.team.pk}:{resource.pk}"]

    def test_review_and_disable_all_public_resource_kinds(self) -> None:
        insight = Insight.objects.create(team=self.team, created_by=self.departing, name="Weekly trends")
        notebook = Notebook.objects.create(team=self.team, created_by=self.user, title="Analysis")
        recording = SessionRecording.objects.create(team=self.team, session_id="offboarding-test-recording")
        insight_share = SharingConfiguration.objects.create(
            team=self.team, insight=insight, enabled=True, password_required=True
        )
        notebook_share = SharingConfiguration.objects.create(
            team=self.team, notebook=notebook, enabled=True, password_required=True, shared_by=self.departing
        )
        recording_share = SharingConfiguration.objects.create(
            team=self.team, recording=recording, enabled=True, shared_by=self.departing
        )
        grace_share = SharingConfiguration.objects.create(
            team=self.team,
            notebook=notebook,
            enabled=True,
            password_required=True,
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        deleted = Insight.objects.create(team=self.team, created_by=self.departing, deleted=True)
        SharingConfiguration.objects.create(team=self.team, insight=deleted, enabled=True)
        other = Notebook.objects.create(team=self.team, created_by=self.user)
        unrelated_share = SharingConfiguration.objects.create(team=self.team, notebook=other, enabled=True)
        response = self.client.get(self.url + "offboarding/")
        assert response.status_code == 200
        review = {item["kind"]: item for item in response.json()}
        assert set(review) == {"insight", "notebook", "recording"}
        assert review["insight"]["password_required"]
        assert review["notebook"]["password_required"]
        assert not review["recording"]["password_required"]
        assert review["insight"]["url"] == f"/project/{self.team.pk}/insights/{insight.short_id}"
        assert review["notebook"]["url"] == f"/project/{self.team.pk}/notebooks/{notebook.short_id}"
        assert review["recording"]["url"] == f"/project/{self.team.pk}/replay/{recording.session_id}"
        grace_share.password_required = False
        grace_share.save(update_fields=["password_required"])
        review = {item["kind"]: item for item in self.client.get(self.url + "offboarding/").json()}
        assert not review["notebook"]["password_required"]
        response = self.client.post(self.url + "offboard/", {"keep": [review["insight"]["id"]]}, format="json")
        assert response.status_code == 204
        insight_share.refresh_from_db()
        assert insight_share.enabled
        for share in (notebook_share, grace_share, recording_share):
            share.refresh_from_db()
            assert not share.enabled
        unrelated_share.refresh_from_db()
        assert unrelated_share.enabled

    def subscription(self, *, creator: User, recipients: str) -> Subscription:
        return Subscription.objects.create(
            team=self.team,
            created_by=creator,
            title="Weekly report",
            target_type="email",
            target_value=recipients,
            frequency="daily",
            interval=1,
            start_date=timezone.now(),
        )

    @parameterized.expand([("delete",), ("post",)])
    def test_removal_disables_only_created_subscriptions(self, method: str) -> None:
        own = self.subscription(creator=self.departing, recipients="other@example.com")
        others = self.subscription(creator=self.user, recipients="other@example.com")
        recipient = self.subscription(creator=self.user, recipients="DEPARTING@example.com,other@example.com")
        only_recipient = self.subscription(creator=self.user, recipients=self.departing.email)
        response = self.client.get(self.url + "offboarding/")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [f"subscription:{own.pk}"]
        assert response.json()[0]["url"] == f"/project/{self.team.pk}/subscriptions/{own.pk}"
        assert response.json()[0]["created_at"] is not None
        response = (
            self.client.delete(self.url)
            if method == "delete"
            else self.client.post(self.url + "offboard/", {}, format="json")
        )
        assert response.status_code == 204
        for subscription in (own, others, recipient, only_recipient):
            subscription.refresh_from_db()
        assert not own.enabled
        assert others.enabled
        assert recipient.enabled and recipient.target_value == "DEPARTING@example.com,other@example.com"
        assert only_recipient.enabled and only_recipient.target_value == self.departing.email

    @parameterized.expand(
        [
            ("email", "first@example.com,second@example.com", "first@example.com,second@example.com"),
            ("slack", "C123|#reports", "C123|#reports"),
            ("teams", "https://example.com/webhook/fake-secret", "example.com"),
        ]
    )
    def test_subscription_destinations_exclude_webhook_credentials(
        self, target_type: str, target_value: str, expected: str
    ) -> None:
        subscription = self.subscription(creator=self.departing, recipients=target_value)
        subscription.target_type = target_type
        subscription.save(update_fields=["target_type"])
        response = self.client.get(self.url + "offboarding/")
        assert response.status_code == 200
        assert response.json()[0]["destination_type"] == target_type
        assert response.json()[0]["destination"] == expected
        assert "fake-secret" not in response.content.decode()

    def test_kept_subscriptions_preserve_recipients(self) -> None:
        kept = self.subscription(creator=self.departing, recipients=f"{self.departing.email},other@example.com")
        disabled = self.subscription(creator=self.departing, recipients="other@example.com")
        response = self.client.post(self.url + "offboard/", {"keep": [f"subscription:{kept.pk}"]}, format="json")
        assert response.status_code == 204
        kept.refresh_from_db()
        disabled.refresh_from_db()
        assert kept.enabled and kept.target_value == f"{self.departing.email},other@example.com"
        assert not disabled.enabled
        assert disabled.target_value == "other@example.com"

    def test_offboarding_does_not_change_subscriptions_in_another_organization(self) -> None:
        other_team = Team.objects.create(organization=Organization.objects.create(name="Other organization"))
        subscription = self.subscription(creator=self.departing, recipients=self.departing.email)
        subscription.team = other_team
        subscription.save(update_fields=["team"])
        assert self.client.get(self.url + "offboarding/").json() == []
        assert self.client.delete(self.url).status_code == 204
        subscription.refresh_from_db()
        assert subscription.enabled
        assert subscription.target_value == self.departing.email

    def test_ai_subscriptions_are_included(self) -> None:
        subscription = self.subscription(creator=self.departing, recipients="reports@example.com")
        subscription.prompt = "Summarize weekly product usage"
        subscription.save(update_fields=["prompt"])
        response = self.client.get(self.url + "offboarding/")
        assert response.status_code == 200
        assert [item["id"] for item in response.json()] == [f"subscription:{subscription.pk}"]

    def test_alerts_can_be_kept_or_disabled_without_changing_recipients(self) -> None:
        insight = Insight.objects.create(team=self.team, created_by=self.departing)
        kept = AlertConfiguration.objects.create(
            team=self.team, insight=insight, created_by=self.departing, name="Keep"
        )
        disabled = AlertConfiguration.objects.create(
            team=self.team, insight=insight, created_by=self.departing, name="Disable"
        )
        unrelated = AlertConfiguration.objects.create(
            team=self.team, insight=insight, created_by=self.user, name="Other"
        )
        kept.subscribed_users.add(self.user)
        response = self.client.get(self.url + "offboarding/")
        assert response.status_code == 200
        assert {item["id"] for item in response.json()} == {f"alert:{kept.pk}", f"alert:{disabled.pk}"}
        assert all(item["kind"] == "alert" for item in response.json())
        response = self.client.post(self.url + "offboard/", {"keep": [f"alert:{kept.pk}"]}, format="json")
        assert response.status_code == 204
        kept.refresh_from_db()
        disabled.refresh_from_db()
        unrelated.refresh_from_db()
        assert kept.enabled
        assert not disabled.enabled
        assert unrelated.enabled
        assert kept.subscribed_users.filter(pk=self.user.pk).exists()

    @patch("products.alerts.backend.platform_ownership.write_moved_alert_edit")
    def test_platform_owned_alert_disables_its_platform_copy(self, write_moved_alert_edit: MagicMock) -> None:
        insight = Insight.objects.create(team=self.team, created_by=self.departing)
        alert = AlertConfiguration.objects.create(
            team=self.team, insight=insight, created_by=self.departing, owner="platform"
        )
        response = self.client.post(self.url + "offboard/", {}, format="json")
        assert response.status_code == 204
        alert.refresh_from_db()
        assert not alert.enabled
        write_moved_alert_edit.assert_called_once_with(team_id=self.team.pk, alert_id=alert.pk, snooze_changed=False)

    @parameterized.expand([("dashboard",), ("insight",), ("notebook",), ("recording",)])
    def test_removal_revokes_hidden_soft_deleted_resources(self, kind: str) -> None:
        models: dict[str, type[Dashboard] | type[Insight] | type[Notebook] | type[SessionRecording]] = {
            "dashboard": Dashboard,
            "insight": Insight,
            "notebook": Notebook,
            "recording": SessionRecording,
        }
        resource = models[kind].objects.create(
            team=self.team, deleted=True, **({"session_id": "deleted-recording"} if kind == "recording" else {})
        )
        share = SharingConfiguration.objects.create(
            team=self.team, **{kind: resource}, enabled=True, shared_by=self.departing
        )
        assert self.client.get(self.url + "offboarding/").json() == []
        assert self.client.post(self.url + "offboard/", {}, format="json").status_code == 204
        resource.deleted = False
        resource.save(update_fields=["deleted"])
        share.refresh_from_db()
        assert not share.enabled
        scope = {
            "dashboard": "Dashboard",
            "insight": "Insight",
            "notebook": "Notebook",
            "recording": "SessionRecording",
        }[kind]
        item_id = (
            resource.short_id
            if isinstance(resource, Notebook)
            else resource.session_id
            if isinstance(resource, SessionRecording)
            else str(resource.pk)
        )
        log = ActivityLog.objects.get(team_id=self.team.pk, scope=scope, item_id=item_id, activity="sharing disabled")
        assert log.user_id == self.user.pk
        assert log.detail is not None
        assert log.detail["changes"][0]["after"] is False

    def test_self_review_hides_inaccessible_projects_but_removal_cleans_them_up(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        hidden_team = Team.objects.create(organization=self.organization, name="Private project")
        AccessControl.objects.create(
            team=hidden_team, resource="project", resource_id=str(hidden_team.pk), access_level="none"
        )
        visible = Dashboard.objects.create(team=self.team, created_by=self.departing)
        hidden = Dashboard.objects.create(team=hidden_team, created_by=self.departing)
        for dashboard in (visible, hidden):
            SharingConfiguration.objects.create(team=dashboard.team, dashboard=dashboard, enabled=True)
        subscription = self.subscription(creator=self.departing, recipients="private@example.com")
        subscription.team = hidden_team
        subscription.save(update_fields=["team"])
        insight = Insight.objects.create(team=hidden_team, created_by=self.departing)
        alert = AlertConfiguration.objects.create(team=hidden_team, insight=insight, created_by=self.departing)
        assert len(self.client.get(self.url + "offboarding/").json()) == 4
        self.client.force_login(self.departing)
        response = self.client.get(self.url + "offboarding/")
        assert response.status_code == 200
        assert [item["team_id"] for item in response.json()] == [self.team.pk]
        assert self.client.post(self.url + "offboard/", {}, format="json").status_code == 204
        assert not SharingConfiguration.objects.filter(dashboard__in=[visible, hidden], enabled=True).exists()
        subscription.refresh_from_db()
        alert.refresh_from_db()
        assert not subscription.enabled
        assert not alert.enabled

    @patch("products.alerts.backend.logic.organization_offboarding.disable_configurations")
    def test_parallel_alert_copy_cleanup_waits_for_commit(self, disable_configurations: MagicMock) -> None:
        insight = Insight.objects.create(team=self.team, created_by=self.departing)
        alert = AlertConfiguration.objects.create(team=self.team, insight=insight, created_by=self.departing)
        with self.captureOnCommitCallbacks(execute=True):
            assert self.client.post(self.url + "offboard/", {}, format="json").status_code == 204
            alert.refresh_from_db()
            assert not alert.enabled
            disable_configurations.assert_not_called()
        disable_configurations.assert_called_once_with(
            "insight", team_id=self.team.pk, legacy_configuration_ids=[alert.pk]
        )

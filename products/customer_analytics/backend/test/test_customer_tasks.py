from datetime import UTC, datetime
from uuid import UUID

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers, status

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.access_control.backend.models.access_control import AccessControl
from products.customer_analytics.backend.logic import customer_tasks
from products.customer_analytics.backend.models import Account, CustomerTask, CustomerTaskActivity
from products.customer_analytics.backend.presentation.views.customer_tasks import (
    CustomerTaskActivityQuerySerializer,
    CustomerTaskCreateSerializer,
    CustomerTaskListQuerySerializer,
    CustomerTaskUpdateSerializer,
)


class CustomerTaskSerializerTest(SimpleTestCase):
    def test_public_writes_reject_internal_properties_and_blank_names(self) -> None:
        create_serializer = CustomerTaskCreateSerializer(data={"name": "  "})
        assert not create_serializer.is_valid()
        assert create_serializer.errors["name"][0] == "Enter a task name."

        properties_serializer = CustomerTaskCreateSerializer(data={"name": "Task", "properties": {"source": "sync"}})
        assert not properties_serializer.is_valid()
        assert "properties" in properties_serializer.errors

        update_serializer = CustomerTaskUpdateSerializer(data={"properties": {"source": "sync"}}, partial=True)
        assert not update_serializer.is_valid()
        assert "properties" in update_serializer.errors

    @parameterized.expand(
        [
            # str.isdigit() accepts this one, but the filter's int() cast does not.
            ("a superscript digit", "²", None),
            ("an unparseable name", "someone", None),
            ("a zero id", "0", None),
            ("an id past int4", "99999999999999999999", None),
            ("a member id", "7", "7"),
            ("a non-decimal digit", "٢", "2"),
            ("the me shorthand", "me", "me"),
        ]
    )
    def test_assigned_to_filter_only_accepts_a_usable_member_id(
        self, _name: str, value: str, expected: str | None
    ) -> None:
        serializer = CustomerTaskListQuerySerializer(data={"assigned_to": value})

        if expected is None:
            assert not serializer.is_valid()
            assert "assigned_to" in serializer.errors
            return
        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["assigned_to"] == expected

    @parameterized.expand(
        [
            ("list", CustomerTaskListQuerySerializer),
            ("activities", CustomerTaskActivityQuerySerializer),
        ]
    )
    def test_page_limit_rejects_zero(self, _name: str, serializer_class: type[serializers.Serializer]) -> None:
        # A zero limit would leave the paginator's next link pointing at the same offset.
        zero_limit = serializer_class(data={"limit": 0})
        assert not zero_limit.is_valid()
        assert "limit" in zero_limit.errors

        smallest_limit = serializer_class(data={"limit": 1})
        assert smallest_limit.is_valid(), smallest_limit.errors
        assert smallest_limit.validated_data["limit"] == 1


class CustomerTaskAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization.available_product_features = [
            {"name": AvailableFeature.ACCESS_CONTROL, "key": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save(update_fields=["available_product_features"])
        self.url = f"/api/projects/{self.team.id}/customer_tasks/"
        self.flag_patcher = patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True)
        self.flag_patcher.start()
        self.addCleanup(self.flag_patcher.stop)

    def test_accountless_create_omits_properties_and_records_activity(self) -> None:
        response = self.client.post(self.url, {"name": "Follow up", "description": None}, format="json")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["account"] is None
        assert "properties" not in response.json()
        task = CustomerTask.objects.unscoped().get(id=response.json()["id"])
        activities_response = self.client.get(f"{self.url}{task.id}/activities/?limit=1&offset=0")
        assert activities_response.status_code == status.HTTP_200_OK
        assert activities_response.json()["count"] == 1
        result = activities_response.json()["results"][0]
        assert result["activity_type"] == "created"
        name_change = next(change for change in result["changes"] if change["field"] == "name")
        assert name_change == {"field": "name", "before": None, "after": "Follow up"}
        activity = CustomerTaskActivity.objects.unscoped().get(task=task)
        assert activity.activity_type == "created"

    def test_account_deletion_preserves_task_and_activities(self) -> None:
        account = Account.objects.for_team(self.team.id).create(team=self.team, name="Temporary account")
        created = self.client.post(
            self.url,
            {"name": "Preserved task", "account_id": str(account.id)},
            format="json",
        )
        task = CustomerTask.objects.unscoped().get(id=created.json()["id"])
        activity_ids = list(CustomerTaskActivity.objects.unscoped().filter(task=task).values_list("id", flat=True))

        account.delete()

        task.refresh_from_db()
        assert task.account_id is None
        assert (
            list(CustomerTaskActivity.objects.unscoped().filter(task=task).values_list("id", flat=True)) == activity_ids
        )

    def test_put_requires_name_while_patch_accepts_partial_fields(self) -> None:
        created = self.client.post(self.url, {"name": "Original task"}, format="json")
        task_url = f"{self.url}{created.json()['id']}/"

        put_response = self.client.put(task_url, {"description": "PUT description"}, format="json")
        patch_response = self.client.patch(task_url, {"description": "PATCH description"}, format="json")

        assert put_response.status_code == status.HTTP_400_BAD_REQUEST
        assert put_response.json()["attr"] == "name"
        assert patch_response.status_code == status.HTTP_200_OK
        assert patch_response.json()["description"] == "PATCH description"

    def test_noop_status_completion_archive_and_restore_lifecycle(self) -> None:
        created = self.client.post(self.url, {"name": "Follow up"}, format="json")
        task_id = created.json()["id"]
        activity_count = CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count()
        updated_at_before = CustomerTask.objects.unscoped().get(id=task_id).updated_at

        noop = self.client.patch(f"{self.url}{task_id}/", {"name": "Follow up"}, format="json")
        assert noop.status_code == status.HTTP_200_OK
        assert CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count() == activity_count
        assert CustomerTask.objects.unscoped().get(id=task_id).updated_at == updated_at_before

        empty = self.client.patch(f"{self.url}{task_id}/", {}, format="json")
        assert empty.status_code == status.HTTP_400_BAD_REQUEST
        assert empty.json()["detail"] == "Change at least one task field."
        completed = self.client.patch(f"{self.url}{task_id}/", {"status": "completed"}, format="json")
        assert completed.status_code == status.HTTP_200_OK
        assert completed.json()["completed_at"] is not None
        assert completed.json()["completed_by"]["id"] == self.user.id

        invalid_transition = self.client.patch(f"{self.url}{task_id}/", {"status": "canceled"}, format="json")
        assert invalid_transition.status_code == status.HTTP_400_BAD_REQUEST
        assert invalid_transition.json()["status"] == "This task can't move from completed to canceled."
        archived = self.client.post(f"{self.url}{task_id}/archive/", {}, format="json")
        activities_before_repeat = CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count()
        repeated_archive = self.client.post(f"{self.url}{task_id}/archive/", {}, format="json")
        assert repeated_archive.status_code == status.HTTP_200_OK
        assert CustomerTaskActivity.objects.unscoped().filter(task_id=task_id).count() == activities_before_repeat
        assert archived.status_code == status.HTTP_200_OK
        blocked = self.client.patch(f"{self.url}{task_id}/", {"name": "Changed"}, format="json")
        assert blocked.status_code == status.HTTP_409_CONFLICT
        assert blocked.json()["detail"] == "Restore this task before editing it."

        restored = self.client.post(f"{self.url}{task_id}/restore/", {}, format="json")
        assert restored.status_code == status.HTTP_200_OK
        assert restored.json()["archived_at"] is None
        reopened = self.client.patch(f"{self.url}{task_id}/", {"status": "open"}, format="json")
        assert reopened.status_code == status.HTTP_200_OK
        assert reopened.json()["completed_at"] is None
        canceled = self.client.patch(f"{self.url}{task_id}/", {"status": "canceled"}, format="json")
        assert canceled.status_code == status.HTTP_200_OK
        assert (
            self.client.patch(f"{self.url}{task_id}/", {"status": "open"}, format="json").status_code
            == status.HTTP_200_OK
        )

    def test_customer_tasks_do_not_expose_object_access_control_actions(self) -> None:
        created = self.client.post(self.url, {"name": "Restricted task"}, format="json")
        task_id = created.json()["id"]

        response = self.client.put(
            f"{self.url}{task_id}/access_controls/",
            {"organization_member": str(self.organization_membership.id), "access_level": "none"},
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_feature_flag_denies_customer_tasks(self) -> None:
        with patch("posthog.permissions.posthog_feature_flag_enabled", return_value=False):
            response = self.client.get(self.url)

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_scopes_allow_reads_and_require_write_for_mutations(self) -> None:
        created = self.client.post(self.url, {"name": "Scoped task"}, format="json")
        task_id = created.json()["id"]

        read_key = self.create_personal_api_key_with_scopes(["customer_task:read"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {read_key}")
        assert self.client.get(f"{self.url}{task_id}/").status_code == status.HTTP_200_OK
        assert (
            self.client.patch(f"{self.url}{task_id}/", {"name": "Denied"}, format="json").status_code
            == status.HTTP_403_FORBIDDEN
        )

        write_key = self.create_personal_api_key_with_scopes(["customer_task:write"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {write_key}")
        assert (
            self.client.patch(f"{self.url}{task_id}/", {"name": "Updated"}, format="json").status_code
            == status.HTTP_200_OK
        )

    def test_child_only_member_cannot_access_parent_tasks(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Environment")
        member = User.objects.create_and_join(self.organization, "child-member@example.com", "testpassword")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="project",
            resource_id=str(self.team.id),
            access_level="none",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=environment,
            resource="project",
            resource_id=str(environment.id),
            access_level="member",
            organization_member=membership,
        )
        CustomerTask.objects.for_team(self.team.id).create(team=self.team, name="Parent task")
        self.client.force_login(member)

        response = self.client.get(f"/api/projects/{environment.id}/customer_tasks/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_child_scoped_api_key_cannot_access_parent_tasks(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Environment")
        CustomerTask.objects.for_team(self.team.id).create(team=self.team, name="Parent task")
        key_value = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="Child-scoped key",
            user=self.user,
            secure_value=hash_key_value(key_value),
            scopes=["customer_task:read"],
            scoped_teams=[environment.id],
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key_value}")

        response = self.client.get(f"/api/projects/{environment.id}/customer_tasks/")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_child_customer_task_access_does_not_grant_parent_task_access(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="Environment")
        member = User.objects.create_and_join(self.organization, "child-editor@example.com", "testpassword")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            access_level="none",
            organization_member=membership,
        )
        AccessControl.objects.create(
            team=environment,
            resource="customer_analytics",
            resource_id=None,
            access_level="editor",
            organization_member=membership,
        )
        self.client.force_login(member)

        response = self.client.post(
            f"/api/projects/{environment.id}/customer_tasks/",
            {"name": "Parent task"},
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not CustomerTask.objects.for_team(self.team.id).exists()

    def test_assignee_can_only_read_and_update_assigned_tasks_and_loses_access_on_reassignment(self) -> None:
        assignee = User.objects.create_and_join(self.organization, "assignee@example.com", "testpassword")
        other_assignee = User.objects.create_and_join(self.organization, "other-assignee@example.com", "testpassword")
        assignee_membership = OrganizationMembership.objects.get(user=assignee, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            access_level="none",
            organization_member=assignee_membership,
        )
        assigned = self.client.post(
            self.url,
            {"name": "Assigned", "assigned_to_id": assignee.id},
            format="json",
        )
        unassigned = self.client.post(self.url, {"name": "Unassigned"}, format="json")
        assigned_id = assigned.json()["id"]

        self.client.force_login(assignee)
        listed_tasks = self.client.get(self.url).json()["results"]
        assert assigned_id in {task["id"] for task in listed_tasks}
        assert unassigned.json()["id"] not in {task["id"] for task in listed_tasks}
        assert all(task["assigned_to"]["id"] == assignee.id for task in listed_tasks)
        assert self.client.get(f"{self.url}{unassigned.json()['id']}/").status_code == status.HTTP_404_NOT_FOUND
        assert (
            self.client.patch(f"{self.url}{assigned_id}/", {"name": "Changed"}, format="json").status_code
            == status.HTTP_200_OK
        )

        self.client.force_login(self.user)
        reassigned = self.client.patch(
            f"{self.url}{assigned_id}/",
            {"assigned_to_id": other_assignee.id},
            format="json",
        )
        assert reassigned.status_code == status.HTTP_200_OK
        self.client.force_login(assignee)
        assert self.client.get(f"{self.url}{assigned_id}/").status_code == status.HTTP_404_NOT_FOUND

    def test_assignee_cannot_cross_account_visibility(self) -> None:
        assignee = User.objects.create_and_join(self.organization, "account-assignee@example.com", "testpassword")
        account = Account.objects.unscoped().create(team=self.team, name="Hidden account")
        created = self.client.post(
            self.url,
            {"name": "Account task", "account_id": str(account.id), "assigned_to_id": assignee.id},
            format="json",
        )
        membership = OrganizationMembership.objects.get(user=assignee, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(account.id),
            access_level="none",
            organization_member=membership,
        )

        self.client.force_login(assignee)
        assert self.client.get(self.url).json()["results"] == []
        assert self.client.get(f"{self.url}{created.json()['id']}/").status_code == status.HTTP_404_NOT_FOUND

    def test_activities_redact_inaccessible_and_malformed_historical_accounts(self) -> None:
        viewer = User.objects.create_and_join(self.organization, "activity-viewer@example.com", "testpassword")
        membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        visible_account = Account.objects.unscoped().create(team=self.team, name="Visible account")
        context_only_visible_account = Account.objects.unscoped().create(team=self.team, name="Context account")
        hidden_account = Account.objects.unscoped().create(team=self.team, name="Hidden account")
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(hidden_account.id),
            access_level="none",
            organization_member=membership,
        )
        task = CustomerTask.objects.for_team(self.team.id).create(team=self.team, name="Account history")
        stored_changes = [
            {
                "field": "account",
                "before": {"id": str(hidden_account.id), "name": hidden_account.name},
                "after": {"id": str(visible_account.id), "name": visible_account.name},
            },
            {
                "field": "account",
                "before": {"id": "not-an-account-id", "name": "Malformed account"},
                "after": ["malformed"],
            },
            {
                "field": "name",
                "before": "Hidden before",
                "after": "Hidden after",
                "before_account_id": str(hidden_account.id),
                "after_account_id": str(hidden_account.id),
            },
            {
                "field": "description",
                "before": "Visible before",
                "after": "Visible after",
                "before_account_id": str(context_only_visible_account.id),
                "after_account_id": str(context_only_visible_account.id),
            },
            {
                "field": "status",
                "before": "open",
                "after": "in_progress",
                "before_account_id": None,
                "after_account_id": None,
            },
        ]
        activity = CustomerTaskActivity.objects.for_team(self.team.id).create(
            team=self.team,
            task=task,
            actor=self.user,
            activity_type="updated",
            changes=stored_changes,
        )
        self.client.force_login(viewer)

        response = self.client.get(f"{self.url}{task.id}/activities/")

        assert response.status_code == status.HTTP_200_OK
        changes = response.json()["results"][0]["changes"]
        assert changes[0] == {
            "field": "account",
            "before": {"id": None, "name": "Restricted account"},
            "after": {"id": str(visible_account.id), "name": visible_account.name},
        }
        assert changes[1] == {
            "field": "account",
            "before": {"id": None, "name": "Restricted account"},
            "after": {"id": None, "name": "Restricted account"},
        }
        assert changes[2] == {"field": "name", "before": None, "after": None}
        assert changes[3] == {
            "field": "description",
            "before": "Visible before",
            "after": "Visible after",
        }
        assert changes[4] == {"field": "status", "before": "open", "after": "in_progress"}
        activity.refresh_from_db()
        assert activity.changes == stored_changes

    def test_cross_team_tasks_are_not_listed(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        CustomerTask.objects.unscoped().create(team=other_team, name="Other team task")

        response = self.client.get(self.url)

        assert response.status_code == status.HTTP_200_OK
        assert all(task["name"] != "Other team task" for task in response.json()["results"])

    def test_archived_tasks_are_retrievable_but_not_active_or_editable(self) -> None:
        created = self.client.post(self.url, {"name": "Archived task"}, format="json")
        task_id = created.json()["id"]
        assert created.json()["can_edit"] is True
        assert created.json()["can_restore"] is False

        archived = self.client.post(f"{self.url}{task_id}/archive/", {}, format="json")
        assert archived.status_code == status.HTTP_200_OK
        assert archived.json()["can_edit"] is False
        assert archived.json()["can_restore"] is True

        assert self.client.get(f"{self.url}{task_id}/").status_code == status.HTTP_200_OK
        assert all(task["id"] != task_id for task in self.client.get(self.url).json()["results"])
        assert self.client.get(f"{self.url}?archive_state=archived").json()["results"][0]["id"] == task_id
        assert (
            self.client.patch(f"{self.url}{task_id}/", {"name": "No edit"}, format="json").status_code
            == status.HTTP_409_CONFLICT
        )

        viewer = User.objects.create_and_join(self.organization, "task-viewer@example.com", "testpassword")
        viewer_membership = OrganizationMembership.objects.get(user=viewer, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="customer_analytics",
            resource_id=None,
            access_level="viewer",
            organization_member=viewer_membership,
        )
        self.client.force_login(viewer)
        viewer_response = self.client.get(f"{self.url}{task_id}/")
        assert viewer_response.status_code == status.HTTP_200_OK
        assert viewer_response.json()["can_edit"] is False
        assert viewer_response.json()["can_restore"] is False

    def _create_filtering_dataset(self) -> tuple[Account, User]:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save(update_fields=["level"])
        alpha_account = Account.objects.for_team(self.team.id).create(
            team=self.team, name="Alpha account", created_by=self.user
        )
        beta_account = Account.objects.for_team(self.team.id).create(
            team=self.team, name="Beta account", created_by=self.user
        )
        other_assignee = User.objects.create_and_join(self.organization, "filter-assignee@example.com", "testpassword")
        timestamp = {day: datetime(2026, 1, day, tzinfo=UTC) for day in range(1, 6)}
        self._create_ordering_task(
            identifier=10,
            name="Alpha",
            description="Contains the search needle",
            status_value="open",
            account=alpha_account,
            assigned_to=self.user,
            due_at=timestamp[3],
            created_at=timestamp[1],
            updated_at=timestamp[1],
        )
        self._create_ordering_task(
            identifier=11,
            name="Bravo",
            status_value="in_progress",
            account=alpha_account,
            assigned_to=other_assignee,
            due_at=timestamp[1],
            created_at=timestamp[2],
            updated_at=timestamp[2],
        )
        self._create_ordering_task(
            identifier=12,
            name="Charlie",
            status_value="completed",
            account=beta_account,
            assigned_to=None,
            due_at=None,
            created_at=timestamp[3],
            updated_at=timestamp[3],
        )
        self._create_ordering_task(
            identifier=13,
            name="Delta",
            status_value="canceled",
            account=beta_account,
            assigned_to=other_assignee,
            due_at=timestamp[2],
            created_at=timestamp[4],
            updated_at=timestamp[4],
        )
        archived = self._create_ordering_task(
            identifier=14,
            name="Archived",
            status_value="canceled",
            account=beta_account,
            assigned_to=other_assignee,
            due_at=timestamp[4],
            created_at=timestamp[5],
            updated_at=timestamp[5],
        )
        CustomerTask.objects.for_team(self.team.id).filter(id=archived.id).update(archived_at=timestamp[5])
        return alpha_account, other_assignee

    @parameterized.expand(
        [
            ("search", "search", "needle", ("Alpha",)),
            ("account", "account_id", "alpha_account", ("Alpha", "Bravo")),
            ("status", "statuses", "canceled", ("Delta",)),
        ]
    )
    def test_list_applies_scalar_filters(
        self, _name: str, parameter: str, value: str, expected_names: tuple[str, ...]
    ) -> None:
        alpha_account, _ = self._create_filtering_dataset()
        query_value = str(alpha_account.id) if value == "alpha_account" else value

        response = self.client.get(self.url, {parameter: query_value})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == len(expected_names)
        assert {task["name"] for task in response.json()["results"]} == set(expected_names)

    @parameterized.expand(
        [
            ("me", "me", ("Alpha",)),
            ("unassigned", "unassigned", ("Charlie",)),
            ("member_id", "member_id", ("Bravo", "Delta")),
        ]
    )
    def test_list_applies_assignee_filters(self, _name: str, assigned_to: str, expected_names: tuple[str, ...]) -> None:
        _, other_assignee = self._create_filtering_dataset()
        query_value = str(other_assignee.id) if assigned_to == "member_id" else assigned_to

        response = self.client.get(self.url, {"assigned_to": query_value})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == len(expected_names)
        assert {task["name"] for task in response.json()["results"]} == set(expected_names)

    @parameterized.expand(
        [
            ("due_after", "due_after", "2026-01-02T00:00:00Z", ("Alpha", "Delta")),
            ("due_before", "due_before", "2026-01-02T00:00:00Z", ("Bravo",)),
            ("without_due_at", "has_due_at", "false", ("Charlie",)),
        ]
    )
    def test_list_applies_due_filters(
        self, _name: str, parameter: str, value: str, expected_names: tuple[str, ...]
    ) -> None:
        self._create_filtering_dataset()

        response = self.client.get(self.url, {parameter: value})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == len(expected_names)
        assert {task["name"] for task in response.json()["results"]} == set(expected_names)

    def test_list_archive_state_all_includes_active_and_archived_tasks(self) -> None:
        self._create_filtering_dataset()

        response = self.client.get(self.url, {"archive_state": "all"})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 5
        assert {task["name"] for task in response.json()["results"]} == {
            "Alpha",
            "Archived",
            "Bravo",
            "Charlie",
            "Delta",
        }

    def test_list_applies_ordering_limit_and_offset(self) -> None:
        self._create_filtering_dataset()

        response = self.client.get(self.url, {"ordering": "-name", "limit": "2", "offset": "1"})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["count"] == 4
        assert [task["name"] for task in response.json()["results"]] == ["Charlie", "Bravo"]

    @parameterized.expand(
        [
            ("list",),
            ("activities",),
        ]
    )
    def test_page_limit_below_one_is_rejected(self, endpoint: str) -> None:
        created = self.client.post(self.url, {"name": "Paged task"}, format="json")
        url = self.url if endpoint == "list" else f"{self.url}{created.json()['id']}/activities/"

        response = self.client.get(url, {"limit": "0"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def _create_ordering_task(
        self,
        *,
        identifier: int,
        name: str,
        status_value: str,
        account: Account | None,
        assigned_to: User | None,
        due_at: datetime | None,
        description: str | None = None,
        created_at: datetime,
        updated_at: datetime,
    ) -> CustomerTask:
        task = CustomerTask.objects.for_team(self.team.id).create(
            id=UUID(int=identifier),
            team=self.team,
            name=name,
            description=description,
            status=status_value,
            account=account,
            assigned_to=assigned_to,
            due_at=due_at,
            completed_at=created_at if status_value == "completed" else None,
        )
        CustomerTask.objects.for_team(self.team.id).filter(id=task.id).update(
            created_at=created_at, updated_at=updated_at
        )
        return task

    def _create_ordering_dataset(self) -> None:
        alpha_account = Account.objects.for_team(self.team.id).create(team=self.team, name="alpha account")
        bravo_account = Account.objects.for_team(self.team.id).create(team=self.team, name="Bravo account")
        alice = User.objects.create_and_join(self.organization, "alice@example.com", "testpassword")
        User.objects.filter(id=alice.id).update(first_name="aLiCe", last_name="Able")
        zoe = User.objects.create_and_join(self.organization, "zoe@example.com", "testpassword")
        User.objects.filter(id=zoe.id).update(first_name="ZoE", last_name="Zed")
        timestamp = {day: datetime(2026, 1, day, tzinfo=UTC) for day in range(1, 5)}
        self._create_ordering_task(
            identifier=1,
            name="bravo",
            status_value="canceled",
            account=bravo_account,
            assigned_to=zoe,
            due_at=timestamp[2],
            created_at=timestamp[3],
            updated_at=timestamp[3],
        )
        self._create_ordering_task(
            identifier=2,
            name="Alpha",
            status_value="open",
            account=alpha_account,
            assigned_to=alice,
            due_at=timestamp[1],
            created_at=timestamp[1],
            updated_at=timestamp[4],
        )
        self._create_ordering_task(
            identifier=3,
            name="charlie",
            status_value="in_progress",
            account=bravo_account,
            assigned_to=zoe,
            due_at=timestamp[2],
            created_at=timestamp[4],
            updated_at=timestamp[1],
        )
        self._create_ordering_task(
            identifier=4,
            name="Delta",
            status_value="completed",
            account=None,
            assigned_to=None,
            due_at=None,
            created_at=timestamp[2],
            updated_at=timestamp[2],
        )

    @parameterized.expand(
        [
            ("name", ("Alpha", "bravo", "charlie", "Delta"), ("Delta", "charlie", "bravo", "Alpha")),
            ("status", ("Alpha", "charlie", "Delta", "bravo"), ("bravo", "Delta", "charlie", "Alpha")),
            ("assigned_to", ("Alpha", "bravo", "charlie", "Delta"), ("bravo", "charlie", "Alpha", "Delta")),
            ("due_at", ("Alpha", "bravo", "charlie", "Delta"), ("bravo", "charlie", "Alpha", "Delta")),
            ("updated_at", ("charlie", "Delta", "bravo", "Alpha"), ("Alpha", "bravo", "Delta", "charlie")),
            ("account", ("Alpha", "bravo", "charlie", "Delta"), ("bravo", "charlie", "Alpha", "Delta")),
            ("created_at", ("Alpha", "Delta", "bravo", "charlie"), ("charlie", "bravo", "Delta", "Alpha")),
        ]
    )
    def test_logic_orders_task_columns(
        self, ordering: str, ascending: tuple[str, ...], descending: tuple[str, ...]
    ) -> None:
        self._create_ordering_dataset()

        ascending_tasks = customer_tasks._apply_ordering(CustomerTask.objects.for_team(self.team.id), ordering)
        descending_tasks = customer_tasks._apply_ordering(CustomerTask.objects.for_team(self.team.id), f"-{ordering}")

        assert list(ascending_tasks.values_list("name", flat=True)) == list(ascending)
        assert list(descending_tasks.values_list("name", flat=True)) == list(descending)

    @parameterized.expand(
        [
            ("name",),
            ("-name",),
            ("status",),
            ("-status",),
            ("assigned_to",),
            ("-assigned_to",),
            ("due_at",),
            ("-due_at",),
            ("updated_at",),
            ("-updated_at",),
            ("account",),
            ("-account",),
            ("created_at",),
            ("-created_at",),
        ]
    )
    def test_logic_ordering_uses_id_tie_breaker(self, ordering: str) -> None:
        timestamp = datetime(2026, 1, 1, tzinfo=UTC)
        self._create_ordering_task(
            identifier=1,
            name="Task",
            description="Zulu",
            status_value="open",
            account=None,
            assigned_to=None,
            due_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._create_ordering_task(
            identifier=2,
            name="Task",
            description="Alpha",
            status_value="open",
            account=None,
            assigned_to=None,
            due_at=timestamp,
            created_at=timestamp,
            updated_at=timestamp,
        )

        queryset = customer_tasks._apply_ordering(CustomerTask.objects.for_team(self.team.id), ordering)

        assert list(queryset.values_list("description", flat=True)) == ["Zulu", "Alpha"]

    @parameterized.expand(
        [
            ("name",),
            ("-name",),
            ("status",),
            ("-status",),
            ("assigned_to",),
            ("-assigned_to",),
            ("due_at",),
            ("-due_at",),
            ("updated_at",),
            ("-updated_at",),
            ("account",),
            ("-account",),
            ("created_at",),
            ("-created_at",),
        ]
    )
    def test_list_accepts_task_ordering(self, ordering: str) -> None:
        response = self.client.get(self.url, {"ordering": ordering})

        assert response.status_code == status.HTTP_200_OK

    def test_update_validates_the_final_account_and_assignee_together(self) -> None:
        assignee = User.objects.create_and_join(self.organization, "final-state@example.com", "testpassword")
        account = Account.objects.unscoped().create(team=self.team, name="Final-state account")
        membership = OrganizationMembership.objects.get(user=assignee, organization=self.organization)
        AccessControl.objects.create(
            team=self.team,
            resource="account",
            resource_id=str(account.id),
            access_level="none",
            organization_member=membership,
        )
        created = self.client.post(self.url, {"name": "Final-state task"}, format="json")

        response = self.client.patch(
            f"{self.url}{created.json()['id']}/",
            {"account_id": str(account.id), "assigned_to_id": assignee.id},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["assigned_to_id"] == (
            "This person can't access the selected account. Choose another assignee or remove the account link."
        )

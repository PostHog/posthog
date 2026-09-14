from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl
from products.access_control.backend.models.access_control import AccessControl
from products.data_modeling.backend.facade import api
from products.data_modeling.backend.models.datawarehouse_saved_query import DataWarehouseSavedQuery


class TestSavedQueryReads(BaseTest):
    @parameterized.expand(
        [
            ("legacy_viewer", False, "viewer"),
            ("legacy_editor", False, "editor"),
            ("most_specific_viewer", True, "viewer"),
            ("most_specific_editor", True, "editor"),
        ]
    )
    def test_allowed_saved_query_ids_preserves_object_grants(
        self, _name: str, most_specific: bool, required_level: AccessControlLevel
    ) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.uses_most_specific_access_resolution = most_specific
        self.organization.save(update_fields=["available_product_features", "uses_most_specific_access_resolution"])
        member = self._create_user("member@example.com")
        membership = OrganizationMembership.objects.get(user=member, organization=self.organization)
        AccessControl.objects.create(team=self.team, resource="warehouse_objects", access_level="none")
        readable = DataWarehouseSavedQuery.objects.create(team=self.team, name="readable")
        editable = DataWarehouseSavedQuery.objects.create(team=self.team, name="editable")
        ungranted = DataWarehouseSavedQuery.objects.create(team=self.team, name="ungranted")
        owned = DataWarehouseSavedQuery.objects.create(team=self.team, name="owned", created_by=member)
        DataWarehouseSavedQuery.objects.create(team=self.team, name="deleted", deleted=True, created_by=member)
        other_team = Team.objects.create(organization=self.organization, name="other")
        DataWarehouseSavedQuery.objects.create(team=other_team, name="other", created_by=member)
        for saved_query, level in [(readable, "viewer"), (editable, "editor")]:
            AccessControl.objects.create(
                team=self.team,
                resource="warehouse_view",
                resource_id=str(saved_query.id),
                organization_member=membership,
                access_level=level,
            )

        access = UserAccessControl(member, team=self.team)
        expected = frozenset({editable.id, owned.id} | ({readable.id} if required_level == "viewer" else set()))
        assert api.allowed_saved_query_ids(self.team.id, access, required_level=required_level) == expected
        with self.assertNumQueries(0):
            assert api.allowed_saved_query_ids(self.team.id, access, required_level=required_level) == expected

        narrowed = api.allowed_saved_query_ids(
            self.team.id, access, required_level=required_level, ids=[owned.id, ungranted.id]
        )
        assert narrowed == frozenset({owned.id})
        with self.assertNumQueries(0):
            assert (
                api.allowed_saved_query_ids(self.team.id, access, required_level=required_level, ids=[]) == frozenset()
            )

        membership.level = OrganizationMembership.Level.ADMIN
        membership.save(update_fields=["level"])
        admin = UserAccessControl(member, team=self.team)
        assert api.allowed_saved_query_ids(self.team.id, admin, required_level=required_level) == frozenset(
            {readable.id, editable.id, ungranted.id, owned.id}
        )

from posthog.test.base import BaseTest

from rest_framework import serializers

from posthog.api.scoped_related_fields import OrgScopedPrimaryKeyRelatedField, TeamScopedPrimaryKeyRelatedField
from posthog.models import Organization, Team
from posthog.models.uploaded_media import UploadedMedia

from products.dashboards.backend.models.dashboard import Dashboard


class TestTeamScopedPrimaryKeyRelatedField(BaseTest):
    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="Other Team")
        self.dashboard_own = Dashboard.objects.create(team=self.team, name="Own Dashboard")
        self.dashboard_other = Dashboard.objects.create(team=self.other_team, name="Other Dashboard")

    def _make_field(self, context: dict) -> TeamScopedPrimaryKeyRelatedField:
        field = TeamScopedPrimaryKeyRelatedField(queryset=Dashboard.objects.all())
        parent: serializers.Serializer = serializers.Serializer(context=context)
        field.bind("test_field", parent)
        return field  # ty: ignore[invalid-return-type]

    def test_filters_by_team_id(self):
        field = self._make_field({"team_id": self.team.id})
        qs = field.get_queryset()
        assert self.dashboard_own in qs
        assert self.dashboard_other not in qs

    def test_returns_none_queryset_when_no_team_id(self):
        field = self._make_field({})
        qs = field.get_queryset()
        assert qs.count() == 0

    def test_returns_none_when_base_queryset_is_none(self):
        field = TeamScopedPrimaryKeyRelatedField(queryset=None)
        parent: serializers.Serializer = serializers.Serializer(context={"team_id": self.team.id})
        field.bind("test_field", parent)
        assert field.get_queryset() is None


class TestOrgScopedPrimaryKeyRelatedField(BaseTest):
    def setUp(self):
        super().setUp()
        self.other_org = Organization.objects.create(name="Other Org")
        self.other_team = Team.objects.create(organization=self.other_org, name="Other Org Team")
        self.media_own = UploadedMedia.objects.create(
            team=self.team,
            created_by=self.user,
            media_location="http://example.com/own.png",
            content_type="image/png",
            file_name="own.png",
        )
        self.media_other = UploadedMedia.objects.create(
            team=self.other_team,
            created_by=self.user,
            media_location="http://example.com/other.png",
            content_type="image/png",
            file_name="other.png",
        )

    def _make_field(self, context: dict) -> OrgScopedPrimaryKeyRelatedField:
        field = OrgScopedPrimaryKeyRelatedField(queryset=UploadedMedia.objects.all())
        parent: serializers.Serializer = serializers.Serializer(context=context)
        field.bind("test_field", parent)
        return field  # ty: ignore[invalid-return-type]

    def test_filters_by_organization(self):
        field = self._make_field({"get_organization": lambda: self.organization})
        qs = field.get_queryset()
        assert self.media_own in qs
        assert self.media_other not in qs

    def test_returns_none_queryset_when_no_org(self):
        field = self._make_field({})
        qs = field.get_queryset()
        assert qs.count() == 0

    def test_returns_none_when_base_queryset_is_none(self):
        field = OrgScopedPrimaryKeyRelatedField(queryset=None)
        parent: serializers.Serializer = serializers.Serializer(context={"get_organization": lambda: self.organization})
        field.bind("test_field", parent)
        assert field.get_queryset() is None

    def test_returns_empty_queryset_when_get_organization_raises(self):
        def raise_attr_error():
            raise AttributeError("Not valid for non-detail routes.")

        field = self._make_field({"get_organization": raise_attr_error})
        qs = field.get_queryset()
        assert qs.count() == 0

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team, User
from posthog.models.access_filter import object_ids_to_q

from products.authz.backend.facade.contracts import ObjectIds
from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestQuerysetAccessFilter(BaseTest):
    @parameterized.expand(
        [
            ("only", False, True, False),
            ("except", True, True, False),
            ("creator_only", False, True, True),
            ("creator_except", True, True, True),
            ("capped", False, False, True),
        ]
    )
    def test_queryset_and_single_object_decisions_agree(
        self, _name: str, excluded: bool, complete: bool, creator_exempt: bool
    ) -> None:
        other = User.objects.create_and_join(self.organization, "other@example.com", "test-password")
        flags = [
            FeatureFlag.objects.create(team=self.team, key="first", created_by=other),
            FeatureFlag.objects.create(team=self.team, key="own", created_by=self.user),
            FeatureFlag.objects.create(team=self.team, key="no-creator", created_by=None),
        ]
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        FeatureFlag.objects.create(team=other_team, key="other-project", created_by=self.user)
        result = ObjectIds(
            ids=frozenset({str(flags[0].pk)}) if complete else frozenset(),
            excluded=excluded,
            complete=complete,
            creator_exempt=creator_exempt,
        )
        expected = [
            flag.pk
            for flag in flags
            if result.allows(str(flag.pk), created_by_user_id=flag.created_by_id, subject_user_id=self.user.pk)
        ]
        queryset = FeatureFlag.objects.filter(team=self.team).order_by("id")
        filtered = queryset.filter(object_ids_to_q(result, subject_user_id=self.user.pk))
        assert list(filtered.values_list("id", flat=True)) == expected
        assert list(filtered.values_list("id", flat=True)[:1]) == expected[:1]

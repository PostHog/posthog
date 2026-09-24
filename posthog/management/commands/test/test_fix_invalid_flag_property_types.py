from io import StringIO

from posthog.test.base import BaseTest

from django.core.management import call_command

from posthog.models import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag


class TestFixInvalidFlagPropertyTypes(BaseTest):
    def test_fixes_v1_rows_and_skips_other_config_formats(self):
        other_team = Team.objects.create(organization=self.organization, name="other")
        invalid_groups = [{"properties": [{"key": "plan", "type": "event", "value": "pro"}], "rollout_percentage": 100}]
        unsupported = FeatureFlag.objects.create(
            team=other_team, key="v2-flag", created_by=self.user, filters={"version": 2, "groups": invalid_groups}
        )
        v1_flag = FeatureFlag.objects.create(
            team=self.team, key="v1-flag", created_by=self.user, filters={"groups": invalid_groups}
        )
        object_groups = FeatureFlag.objects.create(
            team=other_team, key="object-groups", created_by=self.user, filters={"groups": {"properties": "junk"}}
        )

        out = StringIO()
        call_command("fix_invalid_flag_property_types", "--live-run", stdout=out)

        unsupported.refresh_from_db()
        assert unsupported.filters == {"version": 2, "groups": invalid_groups}
        v1_flag.refresh_from_db()
        assert v1_flag.filters["groups"][0]["properties"][0]["type"] == "person"
        object_groups.refresh_from_db()
        assert object_groups.filters == {"groups": {"properties": "junk"}}
        assert f"Flag id={unsupported.id} team_id={other_team.id} key='v2-flag': config format is not 1, skipped" in (
            out.getvalue()
        )
        assert "1 properties fixed, 0 unfixable, 1 flags skipped" in out.getvalue()

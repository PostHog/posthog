from posthog.test.base import BaseTest
from unittest.mock import patch

from products.autoresearch.backend.access import has_autoresearch_access


class TestAutoresearchAccess(BaseTest):
    @patch("products.autoresearch.backend.access.posthoganalytics.feature_enabled", return_value=True)
    def test_sends_both_organization_and_project_groups(self, feature_enabled: object) -> None:
        assert has_autoresearch_access(self.user, team_id=self.team.pk) is True

        _, kwargs = feature_enabled.call_args  # type: ignore[attr-defined]
        assert kwargs["groups"] == {
            "project": str(self.team.pk),
            "organization": str(self.team.organization_id),
        }
        assert kwargs["group_properties"] == {
            "project": {"id": str(self.team.pk)},
            "organization": {"id": str(self.team.organization_id)},
        }

    @patch("products.autoresearch.backend.access.posthoganalytics.feature_enabled", return_value=True)
    def test_uses_the_supplied_organization_without_a_team_lookup(self, feature_enabled: object) -> None:
        with self.assertNumQueries(0):
            assert has_autoresearch_access(self.user, team_id=self.team.pk, organization_id="abc") is True

        _, kwargs = feature_enabled.call_args  # type: ignore[attr-defined]
        assert kwargs["groups"]["organization"] == "abc"

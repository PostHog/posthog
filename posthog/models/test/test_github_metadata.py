from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models.github_metadata import (
    github_organization_group_properties,
    normalize_github_account_type,
    project_github_metadata_onto_organization,
)


class TestGitHubMetadata(SimpleTestCase):
    @parameterized.expand(
        [
            ("Organization", "organization"),
            ("User", "personal"),
            (None, None),
            ("Bot", None),
        ]
    )
    def test_normalize_github_account_type(self, owner_type, expected):
        assert normalize_github_account_type(owner_type) == expected

    def test_group_properties_omit_unknown_values(self):
        assert github_organization_group_properties(account_type="organization") == {
            "github_account_type": "organization"
        }
        assert github_organization_group_properties(
            account_type="personal", repository_selection="all", repository_count=3
        ) == {
            "github_account_type": "personal",
            "github_repository_selection": "all",
            "github_repository_count": 3,
        }

    @patch("posthog.models.github_metadata.posthoganalytics.group_identify")
    def test_projection_uses_organization_group_key_and_returns_true(self, mock_group_identify):
        org_uuid = "018f-org-uuid"
        assert (
            project_github_metadata_onto_organization(
                organization_id=org_uuid,
                account_type="organization",
                repository_selection="selected",
                repository_count=7,
            )
            is True
        )
        mock_group_identify.assert_called_once_with(
            "organization",
            org_uuid,
            properties={
                "github_account_type": "organization",
                "github_repository_selection": "selected",
                "github_repository_count": 7,
            },
        )

    @patch("posthog.models.github_metadata.posthoganalytics.group_identify")
    def test_projection_noop_when_nothing_known(self, mock_group_identify):
        assert project_github_metadata_onto_organization(organization_id="org", account_type=None) is False
        mock_group_identify.assert_not_called()

    @patch("posthog.models.github_metadata.posthoganalytics.group_identify", side_effect=Exception("boom"))
    def test_projection_swallows_errors(self, _mock_group_identify):
        assert project_github_metadata_onto_organization(organization_id="org", account_type="organization") is False

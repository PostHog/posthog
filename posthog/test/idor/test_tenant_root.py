"""Unit tests for the tenant-root case registry."""

from __future__ import annotations

import unittest

from posthog.test.idor.tenant_root import VictimContext, all_cases, get_case


class TestTenantRootRegistry(unittest.TestCase):
    def test_five_known_cases_registered(self) -> None:
        names = {case.name for case in all_cases()}
        assert names == {
            "OrganizationViewSet",
            "ProjectViewSet",
            "RootProjectViewSet",
            "ProjectEnvironmentsViewSet",
            "RootTeamViewSet",
        }

    def test_organization_url_uses_org_uuid(self) -> None:
        case = get_case("OrganizationViewSet")
        assert case is not None
        url = case.build_url(VictimContext(org_uuid="org-1", project_pk=2, team_pk=3))
        assert url == "/api/organizations/org-1/"

    def test_project_url_nested_under_org(self) -> None:
        case = get_case("ProjectViewSet")
        assert case is not None
        url = case.build_url(VictimContext(org_uuid="org-1", project_pk=2, team_pk=3))
        assert url == "/api/organizations/org-1/projects/2/"

    def test_root_project_url_is_flat(self) -> None:
        case = get_case("RootProjectViewSet")
        assert case is not None
        url = case.build_url(VictimContext(org_uuid="org-1", project_pk=2, team_pk=3))
        assert url == "/api/projects/2/"

    def test_project_environments_nested_under_project(self) -> None:
        case = get_case("ProjectEnvironmentsViewSet")
        assert case is not None
        url = case.build_url(VictimContext(org_uuid="org-1", project_pk=2, team_pk=3))
        assert url == "/api/projects/2/environments/3/"

    def test_root_team_url_is_flat(self) -> None:
        case = get_case("RootTeamViewSet")
        assert case is not None
        url = case.build_url(VictimContext(org_uuid="org-1", project_pk=2, team_pk=3))
        assert url == "/api/environments/3/"


if __name__ == "__main__":
    unittest.main()

"""Unit tests for URLStructure and parse_url_pattern.

These run without Django; they exercise the regex parser directly.
"""

from __future__ import annotations

import unittest

from posthog.test.idor.url_structure import URLStructure, parse_url_pattern


class TestParseURLPattern(unittest.TestCase):
    def test_simple_projects_detail(self) -> None:
        pattern = r"^projects/(?P<parent_lookup_project_id>[^/.]+)/annotations/(?P<pk>[^/.]+)/?$"
        s = parse_url_pattern(pattern)
        assert s is not None
        assert s.root == "projects"
        assert s.root_kwarg == "parent_lookup_project_id"
        assert s.resource_prefix == "annotations"
        assert s.pk_kwarg == "pk"
        assert s.intermediate_parents == []

    def test_simple_environments_detail(self) -> None:
        pattern = r"^environments/(?P<parent_lookup_team_id>[^/.]+)/session_recordings/(?P<pk>[^/.]+)/?$"
        s = parse_url_pattern(pattern)
        assert s is not None
        assert s.root == "environments"
        assert s.root_kwarg == "parent_lookup_team_id"
        assert s.resource_prefix == "session_recordings"
        assert s.pk_kwarg == "pk"

    def test_simple_organizations_detail(self) -> None:
        pattern = r"^organizations/(?P<parent_lookup_organization_id>[^/.]+)/plugins/(?P<pk>[^/.]+)/?$"
        s = parse_url_pattern(pattern)
        assert s is not None
        assert s.root == "organizations"
        assert s.root_kwarg == "parent_lookup_organization_id"
        assert s.resource_prefix == "plugins"

    def test_nested_parents(self) -> None:
        pattern = (
            r"^environments/(?P<parent_lookup_team_id>[^/.]+)"
            r"/batch_exports/(?P<parent_lookup_batch_export_id>[^/.]+)"
            r"/runs/(?P<pk>[^/.]+)/?$"
        )
        s = parse_url_pattern(pattern)
        assert s is not None
        assert s.root == "environments"
        assert s.intermediate_parents == [("batch_exports", "parent_lookup_batch_export_id")]
        assert s.resource_prefix == "runs"

    def test_format_variant_returns_none(self) -> None:
        pattern = (
            r"^projects/(?P<parent_lookup_project_id>[^/.]+)/annotations/(?P<pk>[^/.]+)/?\.(?P<format>[a-z0-9]+)/?$"
        )
        # The final kwarg is `format`, not a pk — this is a serializer-format variant.
        s = parse_url_pattern(pattern)
        assert s is None

    def test_non_detail_list_returns_none(self) -> None:
        pattern = r"^projects/(?P<parent_lookup_project_id>[^/.]+)/annotations/?$"
        s = parse_url_pattern(pattern)
        assert s is None

    def test_non_detail_collection_with_action_returns_none(self) -> None:
        pattern = r"^projects/(?P<parent_lookup_project_id>[^/.]+)/feature_flags/bulk_update/?$"
        s = parse_url_pattern(pattern)
        assert s is None

    def test_flat_legacy_returns_none(self) -> None:
        # Legacy viewsets not under /projects|environments|organizations/ can't be IDOR-tested
        pattern = r"^feature_flag/(?P<pk>[^/.]+)/?$"
        s = parse_url_pattern(pattern)
        assert s is None

    def test_custom_pk_kwarg(self) -> None:
        # Some viewsets use a custom lookup_url_kwarg
        pattern = r"^projects/(?P<parent_lookup_project_id>[^/.]+)/feature_flags/(?P<short_id>[^/.]+)/?$"
        s = parse_url_pattern(pattern)
        assert s is not None
        assert s.pk_kwarg == "short_id"

    def test_unknown_root_returns_none(self) -> None:
        pattern = r"^weird_root/(?P<parent_lookup_foo_id>[^/.]+)/things/(?P<pk>[^/.]+)/?$"
        s = parse_url_pattern(pattern)
        assert s is None


class TestBuildURL(unittest.TestCase):
    def test_simple(self) -> None:
        s = URLStructure(
            root="projects",
            root_kwarg="parent_lookup_project_id",
            resource_prefix="annotations",
            pk_kwarg="pk",
        )
        assert s.build_url(root_id=42, pk=7) == "/api/projects/42/annotations/7/"

    def test_with_intermediate(self) -> None:
        s = URLStructure(
            root="environments",
            root_kwarg="parent_lookup_team_id",
            resource_prefix="runs",
            pk_kwarg="pk",
            intermediate_parents=[("batch_exports", "parent_lookup_batch_export_id")],
        )
        url = s.build_url(
            root_id=1,
            pk="abc",
            intermediate_ids={"parent_lookup_batch_export_id": "xyz"},
        )
        assert url == "/api/environments/1/batch_exports/xyz/runs/abc/"

    def test_missing_intermediate_raises(self) -> None:
        s = URLStructure(
            root="environments",
            root_kwarg="parent_lookup_team_id",
            resource_prefix="runs",
            pk_kwarg="pk",
            intermediate_parents=[("batch_exports", "parent_lookup_batch_export_id")],
        )
        with self.assertRaises(KeyError):
            s.build_url(root_id=1, pk="abc")


if __name__ == "__main__":
    unittest.main()

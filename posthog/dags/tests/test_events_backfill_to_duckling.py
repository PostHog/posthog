from dataclasses import dataclass

from unittest.mock import patch

from parameterized import parameterized

from posthog.dags.events_backfill_to_duckling import _resolve_duckling_target


@dataclass
class _FakeRow:
    bucket: str | None
    bucket_region: str


class TestResolveDucklingTarget:
    @parameterized.expand(
        [
            # name, catalog, server, expected_bucket, expected_region
            (
                "catalog_wins",
                _FakeRow("catalog-bucket", "us-east-2"),
                _FakeRow("server-bucket", "eu-west-1"),
                "catalog-bucket",
                "us-east-2",
            ),
            (
                "server_used_when_no_catalog",
                None,
                _FakeRow("server-bucket", "eu-west-1"),
                "server-bucket",
                "eu-west-1",
            ),
            (
                "server_used_when_catalog_bucket_blank",
                _FakeRow("", "us-east-2"),
                _FakeRow("server-bucket", "eu-west-1"),
                "server-bucket",
                "eu-west-1",
            ),
        ]
    )
    def test_prefers_stored_bucket(
        self,
        _name: str,
        catalog: _FakeRow | None,
        server: _FakeRow | None,
        expected_bucket: str,
        expected_region: str,
    ) -> None:
        with (
            patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1"),
            patch(
                "posthog.dags.events_backfill_to_duckling.get_ducklake_catalog_for_organization", return_value=catalog
            ),
            patch("posthog.dags.events_backfill_to_duckling.get_duckgres_server_for_organization", return_value=server),
        ):
            target = _resolve_duckling_target(team_id=123)

        assert target.bucket == expected_bucket
        assert target.bucket_region == expected_region
        assert target.organization_id == "org-1"

    def test_falls_back_to_derived_when_no_stored_source(self) -> None:
        with (
            patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1"),
            patch("posthog.dags.events_backfill_to_duckling.get_ducklake_catalog_for_organization", return_value=None),
            patch("posthog.dags.events_backfill_to_duckling.get_duckgres_server_for_organization", return_value=None),
            patch(
                "posthog.dags.events_backfill_to_duckling.derive_duckling_bucket",
                return_value=("derived-bucket", "us-east-1"),
            ) as mock_derive,
        ):
            target = _resolve_duckling_target(team_id=123)

        mock_derive.assert_called_once_with("org-1")
        assert target.bucket == "derived-bucket"
        assert target.bucket_region == "us-east-1"

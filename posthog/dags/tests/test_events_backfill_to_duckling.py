from dataclasses import dataclass

from unittest.mock import patch

from parameterized import parameterized

from posthog.dags.events_backfill_to_duckling import _resolve_duckling_target


@dataclass
class _FakeRow:
    bucket: str | None
    bucket_region: str


class TestResolveDucklingTarget:
    def _resolve(self, catalog: "_FakeRow | None", server: "_FakeRow | None", cp_status: dict | None = None):
        from rest_framework.response import Response

        status_resp = Response(cp_status or {"state": "ready"}, status=200)
        with (
            patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1"),
            patch(
                "posthog.dags.events_backfill_to_duckling.get_ducklake_catalog_for_organization", return_value=catalog
            ),
            patch("posthog.dags.events_backfill_to_duckling.get_duckgres_server_for_organization", return_value=server),
            patch(
                "products.data_warehouse.backend.api.managed_warehouse.status_for",
                return_value=status_resp,
            ) as mock_status,
        ):
            target = _resolve_duckling_target(team_id=123)
        return target, mock_status

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
            ("server_used_when_no_catalog", None, _FakeRow("server-bucket", "eu-west-1"), "server-bucket", "eu-west-1"),
            (
                "server_used_when_catalog_blank",
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
        catalog: "_FakeRow | None",
        server: "_FakeRow | None",
        expected_bucket: str,
        expected_region: str,
    ) -> None:
        target, mock_status = self._resolve(catalog, server)

        assert target.bucket == expected_bucket
        assert target.bucket_region == expected_region
        assert target.organization_id == "org-1"
        # Stored bucket wins — the control plane is never consulted.
        mock_status.assert_not_called()

    @parameterized.expand(
        [
            ("no_rows", None, None),
            ("server_with_null_bucket", None, _FakeRow(None, "us-east-1")),
            ("both_blank", _FakeRow("", "us-east-1"), _FakeRow(None, "us-east-1")),
        ]
    )
    def test_resolves_from_control_plane_when_no_stored_bucket(
        self, _name: str, catalog: "_FakeRow | None", server: "_FakeRow | None"
    ) -> None:
        target, mock_status = self._resolve(catalog, server, cp_status={"bucket": "cp-bucket"})

        mock_status.assert_called_once_with("org-1")
        assert target.bucket == "cp-bucket"
        assert target.bucket_region == "us-east-1"

    @parameterized.expand(
        [
            ("no_rows", None, None),
            ("server_with_null_bucket", None, _FakeRow(None, "us-east-1")),
        ]
    )
    def test_raises_when_no_stored_bucket_and_control_plane_has_none(
        self, _name: str, catalog: "_FakeRow | None", server: "_FakeRow | None"
    ) -> None:
        import pytest

        with pytest.raises(ValueError, match="No S3 bucket resolvable"):
            self._resolve(catalog, server, cp_status={"state": "ready"})

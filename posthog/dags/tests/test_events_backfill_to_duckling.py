from dataclasses import dataclass

from unittest.mock import patch

from parameterized import parameterized

from posthog.dags.events_backfill_to_duckling import _resolve_duckling_target


@dataclass
class _FakeRow:
    bucket: str | None
    bucket_region: str


class TestResolveDucklingTarget:
    def _resolve(
        self,
        server: "_FakeRow | None",
        cp_bucket: str | None = None,
    ):
        with (
            patch("posthog.dags.events_backfill_to_duckling._get_org_id_for_team", return_value="org-1"),
            patch("posthog.dags.events_backfill_to_duckling.get_duckgres_server_for_organization", return_value=server),
            patch(
                "products.data_warehouse.backend.presentation.views.managed_warehouse.cp_bucket_for",
                return_value=cp_bucket,
            ) as mock_cp,
            # The per-environment table-name lookup hits the DB; this suite stays DB-free.
            patch("posthog.dags.events_backfill_to_duckling._resolve_table_names", return_value=("events", "persons")),
        ):
            target = _resolve_duckling_target(team_id=123)
        return target, mock_cp

    @parameterized.expand(
        [
            # The control plane wins over a stored DuckgresServer bucket — a stale,
            # locally-derived stored value must never beat the authoritative name.
            ("server_present_but_stale", _FakeRow("stale-stored-bucket", "eu-west-1")),
            ("no_server", None),
            ("server_blank", _FakeRow("", "eu-west-1")),
        ]
    )
    def test_control_plane_wins_over_stored_server(self, _name: str, server: "_FakeRow | None") -> None:
        target, mock_cp = self._resolve(server=server, cp_bucket="cp-bucket")

        mock_cp.assert_called_once_with("org-1")
        assert target.bucket == "cp-bucket"
        assert target.organization_id == "org-1"

    def test_falls_back_to_stored_server_when_control_plane_unavailable(self) -> None:
        # CP returns nothing (unreachable/unconfigured) — use the known-good stored row.
        target, mock_cp = self._resolve(server=_FakeRow("server-bucket", "eu-west-1"), cp_bucket=None)

        mock_cp.assert_called_once_with("org-1")
        assert target.bucket == "server-bucket"
        assert target.bucket_region == "eu-west-1"

    @parameterized.expand(
        [
            ("no_rows", None),
            ("server_with_null_bucket", _FakeRow(None, "us-east-1")),
            ("server_blank", _FakeRow("", "us-east-1")),
        ]
    )
    def test_raises_when_nothing_can_name_the_bucket(self, _name: str, server: "_FakeRow | None") -> None:
        import pytest

        with pytest.raises(ValueError, match="No S3 bucket resolvable"):
            self._resolve(server=server, cp_bucket=None)

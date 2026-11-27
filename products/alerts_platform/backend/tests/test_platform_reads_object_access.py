from collections.abc import Collection
from dataclasses import replace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import get_configuration, list_configurations
from products.alerts_platform.backend.facade.contracts import PlatformAlertReader, SourceKind, SourceObjectAccess
from products.alerts_platform.backend.logic import source_configs

_READER = PlatformAlertReader(user_id=1, key_scopes=None)


def _viewable_odd_ids(
    *, team_id: int, object_ids: Collection[int | str], reader: PlatformAlertReader
) -> set[int | str]:
    return {object_id for object_id in object_ids if int(object_id) % 2 == 1}


_KINDS = [SourceKind.LOGS.value, SourceKind.METRICS.value]
_CONDITION = {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}


class TestObjectAccessOnReads(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        registered = source_configs.spec
        logs_spec = registered(SourceKind.LOGS)
        assert logs_spec is not None
        guarded = replace(
            logs_spec, object_access=SourceObjectAccess(source_config_key="watched_id", viewable=_viewable_odd_ids)
        )
        patcher = patch.object(
            source_configs, "spec", side_effect=lambda kind: guarded if kind == SourceKind.LOGS else registered(kind)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        with team_scope(self.team.id):
            self.visible, self.hidden, self.unguarded = (
                platform_testing.create_configuration(
                    team_id=self.team.id,
                    name=name,
                    source_kind=source_kind.value,
                    source_config={
                        "filters": {"serviceNames": ["api"]},
                        "condition": _CONDITION,
                        "watched_id": watched_id,
                    },
                    check_interval_minutes=5,
                )
                for name, source_kind, watched_id in (
                    ("Watches 1", SourceKind.LOGS, 1),
                    ("Watches 2", SourceKind.LOGS, 2),
                    ("Metrics watching 2", SourceKind.METRICS, 2),
                )
            )

    @parameterized.expand(
        [
            ("with_a_reader", _READER, {"Watches 1", "Metrics watching 2"}),
            ("internal", None, {"Watches 1", "Watches 2", "Metrics watching 2"}),
        ]
    )
    def test_a_list_leaves_out_alerts_whose_object_the_reader_cannot_view(
        self, _name: str, reader: PlatformAlertReader | None, expected: set[str]
    ) -> None:
        with team_scope(self.team.id):
            page = list_configurations(team_id=self.team.id, source_kinds=_KINDS, limit=10, offset=0, reader=reader)

        assert {configuration.name for configuration in page.configurations} == expected
        assert page.total == len(expected)

    @parameterized.expand(
        [("viewable", "visible", True), ("not_viewable", "hidden", False), ("unguarded_kind", "unguarded", True)]
    )
    def test_a_retrieve_finds_an_alert_only_when_the_reader_can_view_its_object(
        self, _name: str, which: str, found: bool
    ) -> None:
        with team_scope(self.team.id):
            shown = get_configuration(
                team_id=self.team.id, source_kinds=_KINDS, configuration_id=getattr(self, which).id, reader=_READER
            )

        assert (shown is not None) == found

    def test_the_api_leaves_out_alerts_whose_object_the_user_cannot_view(self) -> None:
        self.enterContext(patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True))
        url = f"/api/projects/{self.team.id}/platform_alerts/"

        listed = self.client.get(url)
        hidden = self.client.get(f"{url}{self.hidden.id}/")
        visible = self.client.get(f"{url}{self.visible.id}/")

        assert listed.status_code == status.HTTP_200_OK, listed.json()
        assert {row["name"] for row in listed.json()["results"]} == {"Watches 1", "Metrics watching 2"}
        assert listed.json()["count"] == 2
        assert hidden.status_code == status.HTTP_404_NOT_FOUND
        assert visible.status_code == status.HTTP_200_OK, visible.json()

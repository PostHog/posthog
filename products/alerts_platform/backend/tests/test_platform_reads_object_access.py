from collections.abc import Collection
from dataclasses import replace

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

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


class TestObjectAccessOnReads(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        logs_spec = source_configs.spec(SourceKind.LOGS)
        assert logs_spec is not None
        guarded = replace(
            logs_spec, object_access=SourceObjectAccess(source_config_key="watched_id", viewable=_viewable_odd_ids)
        )
        patcher = patch.object(
            source_configs, "spec", side_effect=lambda kind: guarded if kind == SourceKind.LOGS else None
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        with team_scope(self.team.id):
            self.visible, self.hidden = (
                platform_testing.create_configuration(
                    team_id=self.team.id,
                    name=f"Watches {watched_id}",
                    source_kind=SourceKind.LOGS.value,
                    source_config={"watched_id": watched_id},
                    check_interval_minutes=5,
                )
                for watched_id in (1, 2)
            )

    @parameterized.expand([("with_a_reader", _READER, {"Watches 1"}), ("internal", None, {"Watches 1", "Watches 2"})])
    def test_a_list_leaves_out_alerts_whose_object_the_reader_cannot_view(
        self, _name: str, reader: PlatformAlertReader | None, expected: set[str]
    ) -> None:
        with team_scope(self.team.id):
            page = list_configurations(
                team_id=self.team.id, source_kinds=[SourceKind.LOGS.value], limit=10, offset=0, reader=reader
            )

        assert {configuration.name for configuration in page.configurations} == expected
        assert page.total == len(expected)

    @parameterized.expand([("viewable", "visible", True), ("not_viewable", "hidden", False)])
    def test_a_retrieve_finds_an_alert_only_when_the_reader_can_view_its_object(
        self, _name: str, which: str, found: bool
    ) -> None:
        with team_scope(self.team.id):
            shown = get_configuration(
                team_id=self.team.id,
                source_kinds=[SourceKind.LOGS.value],
                configuration_id=getattr(self, which).id,
                reader=_READER,
            )

        assert (shown is not None) == found

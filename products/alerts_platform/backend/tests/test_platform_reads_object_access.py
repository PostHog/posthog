from collections.abc import Callable, Collection
from dataclasses import replace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import get_configuration, list_configurations
from products.alerts_platform.backend.facade.contracts import PlatformAlertReader, SourceKind, SourceObjectAccess
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.alerts_platform.backend.logic import source_configs

_READER = PlatformAlertReader(user_id=1, key_scopes=None)
_KINDS = [SourceKind.LOGS.value, SourceKind.METRICS.value]
_CONDITION = {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}


class TestObjectAccessOnReads(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        registered = source_configs.spec
        logs_spec = registered(SourceKind.LOGS)
        assert logs_spec is not None
        self.hook_calls: list[tuple[set[int | str], PlatformAlertReader]] = []
        self.specs = {
            SourceKind.LOGS: replace(
                logs_spec,
                object_access=SourceObjectAccess(source_config_key="watched_id", viewable=self._viewable_odd_ids),
            )
        }
        patcher = patch.object(
            source_configs, "spec", side_effect=lambda kind: self.specs.get(kind) or registered(kind)
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

    def _viewable_odd_ids(
        self, *, team_id: int, object_ids: Collection[int | str], reader: PlatformAlertReader
    ) -> set[int | str]:
        self.hook_calls.append((set(object_ids), reader))
        return {object_id for object_id in object_ids if int(object_id) % 2 == 1}

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

    @parameterized.expand(
        [
            (
                "retrieve",
                lambda test: get_configuration(
                    team_id=test.team.id, source_kinds=_KINDS, configuration_id=test.visible.id, reader=_READER
                ),
            ),
            (
                "list_by_id",
                lambda test: list_configurations(
                    team_id=test.team.id,
                    source_kinds=_KINDS,
                    limit=10,
                    offset=0,
                    configuration_ids=[test.visible.id],
                    reader=_READER,
                ),
            ),
        ]
    )
    def test_the_hook_sees_only_the_objects_of_alerts_that_match_the_filters(
        self, _name: str, read: Callable[["TestObjectAccessOnReads"], object]
    ) -> None:
        with team_scope(self.team.id):
            read(self)

        assert [object_ids for object_ids, _reader in self.hook_calls] == [{1}]

    def test_the_hook_is_not_asked_when_no_alert_of_its_kind_matches(self) -> None:
        with team_scope(self.team.id):
            shown = get_configuration(
                team_id=self.team.id, source_kinds=_KINDS, configuration_id=self.unguarded.id, reader=_READER
            )

        assert shown is not None
        assert self.hook_calls == []

    @parameterized.expand([("session", None), ("personal_api_key", ["alert:read", "logs:read"])])
    def test_the_api_asks_the_hook_about_the_requesting_user(self, _name: str, key_scopes: list[str] | None) -> None:
        self.enterContext(patch("posthog.permissions.posthog_feature_flag_enabled", return_value=True))
        if key_scopes is not None:
            self.client.logout()
            self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.create_personal_api_key_with_scopes(key_scopes)}")

        response = self.client.get(f"/api/projects/{self.team.id}/platform_alerts/{self.visible.id}/")

        assert response.status_code == status.HTTP_200_OK, response.json()
        expected = PlatformAlertReader(
            user_id=self.user.id, key_scopes=None if key_scopes is None else frozenset(key_scopes)
        )
        assert [reader for _object_ids, reader in self.hook_calls] == [expected]

    @parameterized.expand([("with_a_reader", _READER, False), ("internal", None, True)])
    def test_a_read_only_kind_shows_a_reader_only_the_alerts_the_platform_holds(
        self, _name: str, reader: PlatformAlertReader | None, source_copy_shown: bool
    ) -> None:
        metrics_spec = source_configs.spec(SourceKind.METRICS)
        assert metrics_spec is not None
        self.specs[SourceKind.METRICS] = replace(metrics_spec, read_only=True)
        with team_scope(self.team.id):
            source_copy, _platform_copy = (
                platform_testing.create_configuration(
                    team_id=self.team.id,
                    name=name,
                    source_kind=SourceKind.METRICS.value,
                    source_config={"filters": {"serviceNames": ["api"]}, "condition": _CONDITION},
                    check_interval_minutes=5,
                    legacy_configuration_id=uuid4(),
                    owner=owner,
                )
                for name, owner in (
                    ("Source-owned copy", PlatformAlertOwner.SOURCE),
                    ("Platform-owned copy", PlatformAlertOwner.PLATFORM),
                )
            )
            page = list_configurations(
                team_id=self.team.id, source_kinds=[SourceKind.METRICS.value], limit=10, offset=0, reader=reader
            )
            shown = get_configuration(
                team_id=self.team.id,
                source_kinds=[SourceKind.METRICS.value],
                configuration_id=source_copy.id,
                reader=reader,
            )

        held = {"Metrics watching 2", "Platform-owned copy"}
        expected = held | {"Source-owned copy"} if source_copy_shown else held
        assert {configuration.name for configuration in page.configurations} == expected
        assert page.total == len(expected)
        assert (shown is not None) == source_copy_shown

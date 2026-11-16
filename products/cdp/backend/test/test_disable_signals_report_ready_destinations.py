import importlib
from types import SimpleNamespace

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.apps import apps

from products.cdp.backend.models.hog_functions.hog_function import HogFunction

MIGRATION = importlib.import_module("products.cdp.backend.migrations.0009_disable_signals_report_ready_destinations")
REPORT_EVENT = {"events": [{"id": "$signals_report_ready", "type": "events"}]}
OTHER_EVENT = {"events": [{"id": "$activity_log_entry_created", "type": "events"}]}


class TestDisableSignalsReportReadyDestinations(BaseTest):
    def _destination(self, name: str, *, filters: dict, enabled: bool = True, deleted: bool = False) -> HogFunction:
        return HogFunction.objects.create(
            team=self.team,
            name=name,
            hog="return event",
            type="internal_destination",
            enabled=enabled,
            deleted=deleted,
            filters=filters,
        )

    def test_disables_only_enabled_destinations_on_the_report_event(self) -> None:
        rows = {
            "on the event": self._destination("on the event", filters=REPORT_EVENT),
            "on the event and another": self._destination(
                "on the event and another", filters={"events": [*OTHER_EVENT["events"], *REPORT_EVENT["events"]]}
            ),
            "other event": self._destination("other event", filters=OTHER_EVENT),
            "already disabled": self._destination("already disabled", filters=REPORT_EVENT, enabled=False),
            "soft-deleted": self._destination("soft-deleted", filters=REPORT_EVENT, deleted=True),
        }
        schema_editor = SimpleNamespace(connection=SimpleNamespace(alias="default"))

        with patch("posthog.plugins.plugin_server_api.publish_message") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                # Twice, because bin/migrate retries a migration that failed part of the way.
                MIGRATION.disable_report_ready_destinations(apps, schema_editor)
                MIGRATION.disable_report_ready_destinations(apps, schema_editor)
                # A worker told before the commit would read and cache the old enabled state.
                publish.assert_not_called()

        enabled = {name: HogFunction.objects.get(id=row.id).enabled for name, row in rows.items()}
        assert enabled == {
            "on the event": False,
            "on the event and another": False,
            "other event": True,
            "already disabled": False,
            "soft-deleted": False,
        }
        reloaded = [call.args for call in publish.call_args_list]
        assert len(reloaded) == 1
        channel, message = reloaded[0]
        assert channel == "reload-hog-functions"
        assert message["teamId"] == self.team.id
        assert sorted(message["hogFunctionIds"]) == sorted(
            [str(rows["on the event"].id), str(rows["on the event and another"].id), str(rows["soft-deleted"].id)]
        )

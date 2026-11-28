from io import StringIO
from uuid import UUID, uuid4

from posthog.test.base import APIBaseTest

from django.core.management import call_command

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.scoping import team_scope

from products.alerts.backend.models.alert import AlertConfiguration, InvestigationStatus
from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts.backend.platform_source_cycle import platform_upsert_of
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.api import upsert_configuration
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner


class TestDetachInsightAlertInvestigationsFromRows(APIBaseTest):
    def _alert(self, *, copy_owner: PlatformAlertOwner | None) -> tuple[AlertConfiguration, UUID]:
        alert = create_insight_alert(self.team, owner=copy_owner or PlatformAlertOwner.SOURCE)
        if copy_owner is None:
            return alert, uuid4()
        upsert = platform_upsert_of(alert)
        assert upsert is not None
        with team_scope(self.team.id):
            upsert_configuration(upsert)
            copy_id = platform_testing.copy_of(alert.id).id
            platform_testing.set_owner(copy_id, copy_owner)
        return alert, copy_id

    def _investigation(self, alert: AlertConfiguration | None, configuration_id: UUID) -> UUID:
        return (
            InsightAlertInvestigation.objects.for_team(self.team.id)
            .create(
                team=self.team,
                alert_configuration=alert,
                configuration_id=configuration_id,
                evaluation_key=f"slot:{uuid4()}",
                kind=InsightAlertInvestigation.Kind.AGENT,
                status=InvestigationStatus.DONE,
            )
            .id
        )

    def _links(self) -> dict[UUID, tuple[UUID | None, UUID]]:
        rows = InsightAlertInvestigation.objects.for_team(self.team.id)
        return {
            row_id: (alert_id, config_id)
            for row_id, alert_id, config_id in rows.values_list("id", "alert_configuration_id", "configuration_id")
        }

    def _run(self, *options: str) -> str:
        out = StringIO()
        call_command(
            "detach_insight_alert_investigations_from_rows", "--team-id", str(self.team.id), *options, stdout=out
        )
        return out.getvalue()

    def test_detaches_only_investigations_of_alerts_the_platform_owns(self) -> None:
        moved, moved_copy = self._alert(copy_owner=PlatformAlertOwner.PLATFORM)
        detached = {self._investigation(moved, moved_copy) for _ in range(3)}
        kept = {
            self._investigation(*self._alert(copy_owner=PlatformAlertOwner.SOURCE)),
            self._investigation(*self._alert(copy_owner=None)),
            self._investigation(None, uuid4()),
        }
        before = self._links()
        activity_before = ActivityLog.objects.filter(team_id=self.team.id).count()

        assert self._run().splitlines()[-1] == "1 teams, 3 investigations to detach (dry run)"
        assert self._links() == before

        assert self._run("--apply", "--batch-size", "2").splitlines()[-1] == "1 teams, 3 investigations detached"
        after = self._links()
        assert {row_id: after[row_id] for row_id in detached} == dict.fromkeys(detached, (None, moved_copy))
        assert {row_id: after[row_id] for row_id in kept} == {row_id: before[row_id] for row_id in kept}
        assert ActivityLog.objects.filter(team_id=self.team.id).count() == activity_before

        assert self._run("--apply").splitlines()[-1] == "1 teams, 0 investigations detached"

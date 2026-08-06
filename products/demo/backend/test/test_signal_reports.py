import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from products.demo.backend.logic.signal_reports import seed_signal_report_for_error_issue
from products.signals.backend.models import SignalReport, SignalReportArtefact


class TestSeedSignalReportForErrorIssue(BaseTest):
    @patch("products.demo.backend.logic.signal_reports.sync_execute")
    def test_seeds_report_artefacts_and_error_issue_link(self, sync_execute) -> None:
        issue_id = "019fd5ec-ec19-7683-8c0c-cab5c3cefb8e"

        report = seed_signal_report_for_error_issue(team_id=self.team.id, issue_id=issue_id, index=0)

        assert report.status == SignalReport.Status.READY
        assert report.signal_count == 1
        assert set(SignalReportArtefact.objects.filter(report=report).values_list("type", flat=True)) == {
            SignalReportArtefact.ArtefactType.SAFETY_JUDGMENT,
            SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
            SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            SignalReportArtefact.ArtefactType.REPO_SELECTION,
        }
        inserted_row = sync_execute.call_args.args[1][0]
        assert json.loads(inserted_row[8]) == {
            "source_product": "error_tracking",
            "source_type": "issue_created",
            "source_id": issue_id,
            "weight": 1.0,
            "report_id": str(report.id),
            "extra": {"demo": True},
            "remediation": None,
        }

    @patch("products.demo.backend.logic.signal_reports.sync_execute")
    def test_is_idempotent(self, sync_execute) -> None:
        issue_id = "019fd5ec-ec19-7683-8c0c-cab5c3cefb8e"

        first = seed_signal_report_for_error_issue(team_id=self.team.id, issue_id=issue_id, index=0)
        second = seed_signal_report_for_error_issue(team_id=self.team.id, issue_id=issue_id, index=0)

        assert first.id == second.id
        assert SignalReport.objects.filter(team=self.team, title=first.title).count() == 1
        assert SignalReportArtefact.objects.filter(report=first).count() == 5
        assert sync_execute.call_count == 2

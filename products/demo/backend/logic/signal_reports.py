import uuid
from dataclasses import dataclass

from django.utils import timezone

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request

from products.signals.backend.artefact_schemas import (
    ActionabilityAssessment,
    ActionabilityChoice,
    Priority,
    PriorityAssessment,
    RepoSelectionResult,
    SafetyJudgment,
    SignalFinding,
)
from products.signals.backend.models import ArtefactAttribution, SignalReport, SignalReportArtefact


@dataclass(frozen=True)
class DemoIssueReportSpec:
    title: str
    summary: str
    priority: Priority
    code_paths: tuple[str, ...]


_REPORT_SPECS = (
    DemoIssueReportSpec(
        title="Prevent expired file links from failing without recovery",
        summary=(
            "Downloads can fail after a signed link expires. The failure is localized to the file-link refresh path "
            "and can be handled by refreshing the link once before showing an error."
        ),
        priority=Priority.P1,
        code_paths=("frontend/src/files/downloadFile.ts", "frontend/src/files/fileLinkLogic.ts"),
    ),
    DemoIssueReportSpec(
        title="Validate malformed upload metadata before processing",
        summary=(
            "A malformed upload payload reaches the processing pipeline and raises an internal exception. Validate "
            "the payload at the boundary and return a useful error instead."
        ),
        priority=Priority.P2,
        code_paths=("backend/uploads/serializers.py", "backend/uploads/tasks.py"),
    ),
    DemoIssueReportSpec(
        title="Handle duplicate team invitations idempotently",
        summary=(
            "Repeated invitation submissions can race and create a duplicate-member error. Treat an existing invite "
            "as success and keep the invitation flow recoverable."
        ),
        priority=Priority.P2,
        code_paths=("frontend/src/team/inviteLogic.ts", "backend/team/invites.py"),
    ),
)


def seed_signal_report_for_error_issue(*, team_id: int, issue_id: str, index: int) -> SignalReport:
    """Create a sanitized Inbox report and bind it to a demo error-tracking issue.

    The binding deliberately uses the production read path: a backing signal whose error-tracking
    `source_id` is the issue UUID. The Issue scene can therefore discover these reports with the same
    source lookup used outside demo projects.
    """
    spec = _REPORT_SPECS[index % len(_REPORT_SPECS)]
    report, _ = SignalReport.objects.get_or_create(
        team_id=team_id,
        title=spec.title,
        defaults={
            "summary": spec.summary,
            "status": SignalReport.Status.READY,
            "signal_count": 1,
            "total_weight": 1.0,
            "promoted_at": timezone.now(),
        },
    )

    attribution = ArtefactAttribution.system()
    if not SignalReportArtefact.objects.filter(report=report).exists():
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=str(report.id),
            content=SafetyJudgment(choice=True),
            attribution=attribution,
            reevaluate_autostart=False,
        )
        SignalReportArtefact.append_finding(
            team_id=team_id,
            report_id=str(report.id),
            content=SignalFinding(
                signal_id=f"demo-error-issue-{issue_id}",
                relevant_code_paths=list(spec.code_paths),
                relevant_commit_hashes={},
                data_queried="Synthetic demo evidence derived from the linked error-tracking issue.",
                verified=True,
            ),
            attribution=attribution,
        )
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=str(report.id),
            content=ActionabilityAssessment(
                explanation="The synthetic failure is localized to the listed demo code paths and has a bounded fix.",
                actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                already_addressed=False,
            ),
            attribution=attribution,
            reevaluate_autostart=False,
        )
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=str(report.id),
            content=PriorityAssessment(
                explanation="The demo issue represents a recurring user-facing failure on a core workflow.",
                priority=spec.priority,
            ),
            attribution=attribution,
            reevaluate_autostart=False,
        )
        SignalReportArtefact.append_status(
            team_id=team_id,
            report_id=str(report.id),
            content=RepoSelectionResult(repository="posthog/posthog", reason="Synthetic demo repository."),
            attribution=attribution,
            reevaluate_autostart=False,
        )

    emit_embedding_request(
        content=f"New error tracking issue created: {spec.title}",
        team_id=team_id,
        product="signals",
        document_type="signal",
        rendering="plain",
        document_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"posthog-demo-signal:{team_id}:{issue_id}")),
        models=[model.value for model in EmbeddingModelName],
        timestamp=timezone.now(),
        metadata={
            "source_product": "error_tracking",
            "source_type": "issue_created",
            "source_id": issue_id,
            "weight": 1.0,
            "report_id": str(report.id),
            "extra": {"demo": True},
            "remediation": None,
        },
    )
    return report

import {
  ArrowCounterClockwiseIcon,
  CopyIcon,
  FileTextIcon,
  MagnifyingGlassIcon,
} from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { InboxDetailFrame } from "@posthog/ui/features/inbox/components/InboxDetailFrame";
import { InboxReportDetailGate } from "@posthog/ui/features/inbox/components/InboxReportDetailGate";
import {
  type InboxBackTarget,
  useInboxBackTarget,
} from "@posthog/ui/features/inbox/hooks/useInboxBackTarget";
import { useInboxRestoreReport } from "@posthog/ui/features/inbox/hooks/useInboxRestoreReport";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { Spinner } from "@radix-ui/themes";
import { useNavigate } from "@tanstack/react-router";

interface DismissedReportDetailProps {
  reportId: string;
  cachedReport?: SignalReport | null;
}

/**
 * Detail view for a terminal report shown in the Archive tab. Read-only re-read
 * of what the report was — summary + evidence — with no triage affordances
 * (archive, discuss, create PR, reviewers): the report is out of the pipeline.
 *
 * Suppressed (user-archived) reports offer a single Restore action. Resolved
 * (implementation PR merged) reports are reference-only — resolving is terminal,
 * so there's nothing to restore and no Restore button is shown.
 *
 * The gate keeps reports on the route that matches their status: a report that
 * is no longer terminal opened here (stale URL or restored elsewhere) is
 * redirected to its current home.
 */
export function DismissedReportDetail({
  reportId,
  cachedReport = null,
}: DismissedReportDetailProps) {
  // Follow the user's path in: if they archived a report while viewing it, the
  // redirect here recorded its origin (Reports / Pulls / Runs) so the back link
  // returns there. Arriving directly (deep link, Archive-tab click, refresh)
  // falls back to "Back to archive".
  const back = useInboxBackTarget({
    to: "/code/inbox/dismissed",
    label: "Back to archive",
  });
  return (
    <InboxReportDetailGate
      reportId={reportId}
      cachedReport={cachedReport}
      backTo="/code/inbox/dismissed"
      backLabel="Back to archive"
      backLinkTo={back.to}
      backLinkLabel={back.label}
      missingCopy="This report couldn't be found. It may have been deleted."
    >
      {(report) => <DismissedReportDetailContent report={report} back={back} />}
    </InboxReportDetailGate>
  );
}

function DismissedReportDetailContent({
  report,
  back,
}: {
  report: SignalReport;
  back: InboxBackTarget;
}) {
  // Resolved reports are terminal (their PR already merged) — nothing to
  // restore, so only suppressed reports get a Restore action.
  const canRestore = report.status === "suppressed";
  return (
    <InboxDetailFrame
      report={report}
      backTo={back.to}
      backLabel={back.label}
      fallbackTitle="Untitled report"
      showDismiss={false}
      primaryAction={
        <>
          {canRestore && <RestoreReportButton report={report} />}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => copyInboxReportLink(report)}
            title="Copy a deep link to this report"
          >
            <CopyIcon size={12} />
          </Button>
        </>
      }
      summarySection={{ Icon: FileTextIcon, title: "Summary" }}
      evidenceSection={{ Icon: MagnifyingGlassIcon, title: "Evidence" }}
    />
  );
}

function RestoreReportButton({ report }: { report: SignalReport }) {
  const restore = useInboxRestoreReport();
  const navigate = useNavigate();

  return (
    <Button
      type="button"
      variant="primary"
      size="sm"
      disabled={restore.isPending}
      className="gap-1"
      title="Restore this report to the inbox"
      onClick={() =>
        restore.mutate(report.id, {
          onSuccess: () => navigate({ to: "/code/inbox/dismissed" }),
        })
      }
    >
      {restore.isPending ? (
        <Spinner size="1" />
      ) : (
        <ArrowCounterClockwiseIcon size={12} />
      )}
      Restore
    </Button>
  );
}

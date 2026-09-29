import { TargetIcon } from "@phosphor-icons/react";
import {
  buildReportCheckRows,
  latestCheckExplanations,
  reportChecksMeta,
  splitReportCheckRows,
} from "@posthog/core/inbox/reportChecks";
import { Button } from "@posthog/quill";
import type { SignalReport, SignalReportCheck } from "@posthog/shared/types";
import { ReportCheckRow } from "@posthog/ui/features/inbox/components/detail/ReportCheckRow";
import { StopReportCheckDialog } from "@posthog/ui/features/inbox/components/detail/StopReportCheckDialog";
import { RightColumnSection } from "@posthog/ui/features/inbox/components/RightColumnSection";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import {
  useCancelReportCheck,
  useReportChecks,
} from "@posthog/ui/features/inbox/hooks/useReportChecks";
import { useState } from "react";

/**
 * What is still watching this report, and what the checks that already ran decided. A check is
 * the one forward-looking row a report carries: an expectation plus the time to test it. Until it
 * produces a verdict nothing else on the page mentions it, so a reader cannot otherwise tell that
 * a check is scheduled, waiting for the report to resolve, or expired without ever running.
 *
 * Hidden entirely when the report has no checks, so the detail does not grow an empty section on
 * the reports that carry none.
 */
export function ReportChecksSection({ report }: { report: SignalReport }) {
  const { data: checksResponse } = useReportChecks(report.id);
  const { data: artefactsResponse } = useInboxReportArtefacts(report.id);
  const cancelCheck = useCancelReportCheck(report.id);
  const [showRetired, setShowRetired] = useState(false);
  const [pendingStop, setPendingStop] = useState<SignalReportCheck | null>(
    null,
  );

  const checks = checksResponse?.results ?? [];
  if (checks.length === 0) return null;

  const rows = buildReportCheckRows(
    checks,
    latestCheckExplanations(artefactsResponse?.results ?? []),
  );
  const { visible, hidden } = splitReportCheckRows(rows);

  return (
    <RightColumnSection
      Icon={TargetIcon}
      title="Follow-up checks"
      collapsible
      rightSlot={
        <span className="cursor-default select-none text-muted-foreground text-xs tabular-nums">
          {reportChecksMeta(checks)}
        </span>
      }
    >
      <div className="flex flex-col gap-1.5">
        {(showRetired ? rows : visible).map((row) => (
          <ReportCheckRow
            key={row.check.id}
            row={row}
            stopping={
              cancelCheck.isPending && cancelCheck.variables === row.check.id
            }
            onStop={setPendingStop}
          />
        ))}
        {hidden.length > 0 && !showRetired && (
          <Button
            variant="link-muted"
            size="xs"
            className="self-start"
            onClick={() => setShowRetired(true)}
          >
            Show {hidden.length} more
          </Button>
        )}
      </div>

      <StopReportCheckDialog
        check={pendingStop}
        onConfirm={async (checkId) => {
          await cancelCheck.mutateAsync(checkId);
          setPendingStop(null);
        }}
        onCancel={() => setPendingStop(null)}
      />
    </RightColumnSection>
  );
}

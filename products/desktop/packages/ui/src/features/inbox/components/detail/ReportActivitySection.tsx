import { ClockCounterClockwiseIcon } from "@phosphor-icons/react";
import { ArtefactLogList } from "@posthog/ui/features/inbox/components/detail/ArtefactLogList";
import { selectUsefulReportActivity } from "@posthog/ui/features/inbox/components/detail/reportActivity";
import { RightColumnSection } from "@posthog/ui/features/inbox/components/RightColumnSection";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import type { ReactElement } from "react";

/**
 * The report's useful work history, shared by every report detail surface.
 * Routine pipeline judgments and task links already appear in their own
 * sections, so repeating them here would hide human-readable progress.
 */
export function ReportActivitySection({
  reportId,
  hideCommitDiffs,
  collapsedNoteCount = 0,
}: {
  reportId: string;
  /** Drop the per-commit diff toggle (PR detail shows the full diff already). */
  hideCommitDiffs?: boolean;
  collapsedNoteCount?: number;
}): ReactElement | null {
  // Agents append artefacts while the report is open, so the app-wide
  // 5-minute stale time would hide progress from someone watching the report.
  const { data: artefactsResp } = useInboxReportArtefacts(reportId, {
    staleTime: 10_000,
    refetchInterval: 20_000,
  });
  const artefacts = selectUsefulReportActivity(artefactsResp?.results ?? []);

  if (artefacts.length === 0 && collapsedNoteCount === 0) return null;

  return (
    <RightColumnSection
      Icon={ClockCounterClockwiseIcon}
      title="Activity"
      collapsible
      defaultCollapsed
      rightSlot={
        <span className="cursor-default select-none text-[12px] text-gray-10 tabular-nums">
          {artefacts.length} entr{artefacts.length === 1 ? "y" : "ies"}
          {collapsedNoteCount > 0 &&
            ` · ${collapsedNoteCount} ${collapsedNoteCount === 1 ? "confirmation" : "confirmations"}`}
        </span>
      }
    >
      {collapsedNoteCount > 0 && (
        <p className="mb-3 text-gray-10 text-xs">
          Corroborated {collapsedNoteCount} more{" "}
          {collapsedNoteCount === 1 ? "time" : "times"} by a scout, with nothing
          new to add.
        </p>
      )}
      <ArtefactLogList
        reportId={reportId}
        artefacts={artefacts}
        hideCommitDiffs={hideCommitDiffs}
      />
    </RightColumnSection>
  );
}

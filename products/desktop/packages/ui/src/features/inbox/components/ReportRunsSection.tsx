import { TerminalIcon } from "@phosphor-icons/react";
import { humanizeIdentifier } from "@posthog/core/inbox/activityLog";
import type { SignalReport } from "@posthog/shared/types";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { useReportTasks } from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { useOpenTask } from "@posthog/ui/router/useOpenTask";

export function ReportRunsSection({ report }: { report: SignalReport }) {
  const { data: runs } = useReportTasks(report.id, report.status);
  const openTask = useOpenTask();

  if (!runs || runs.length === 0) return null;

  return (
    <DetailSection
      Icon={TerminalIcon}
      title="Runs"
      collapsible
      defaultCollapsed
      rightSlot={
        <span className="text-[12px] text-gray-10 tabular-nums">
          {runs.length}
        </span>
      }
    >
      <div className="flex flex-col gap-1">
        {runs.map(({ task, purposeLabel, startedAt }) => (
          <button
            key={task.id}
            type="button"
            className="flex min-w-0 items-center gap-2 rounded-(--radius-1) px-1 py-1.5 text-left hover:bg-(--gray-3)"
            onClick={() => void openTask(task)}
          >
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-(--gray-8)" />
            <span className="min-w-0 flex-1 truncate font-medium text-[12px] text-gray-11">
              {purposeLabel}
            </span>
            {task.latest_run?.status && (
              <span className="shrink-0 text-[11px] text-gray-10">
                {humanizeIdentifier(task.latest_run.status)}
              </span>
            )}
            <RelativeTimestamp
              timestamp={startedAt}
              className="shrink-0 text-[11px]"
            />
          </button>
        ))}
      </div>
    </DetailSection>
  );
}

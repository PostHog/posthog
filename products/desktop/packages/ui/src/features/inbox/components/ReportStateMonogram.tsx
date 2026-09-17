import { FileTextIcon } from "@phosphor-icons/react";
import { isAgentRunReport } from "@posthog/core/inbox/reportMembership";
import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import {
  resolveRunVariant,
  VARIANT_META,
  type VariantMeta,
} from "@posthog/ui/features/inbox/components/AgentRunCard";

/**
 * Run-state meta for a report that hasn't been triaged yet (queued, live, or
 * failed), null for the rest. Priority is stamped when a report becomes ready,
 * so these are exactly the reports a priority monogram can't describe — the
 * old inbox showed them run-state-shaped on its Runs tab.
 */
export function reportRunState(report: SignalReport): VariantMeta | null {
  if (!isAgentRunReport(report) && report.status !== "failed") return null;
  return VARIANT_META[resolveRunVariant(report)];
}

/**
 * The report's leading glyph: a run-state orb (queued / running / failed) while
 * the report is still moving, otherwise a neutral report glyph. Priority is
 * deliberately not worn here — it reads as muted text in the row's meta line,
 * so rows lead with the title rather than a taxonomy.
 */
export function ReportStateMonogram({ report }: { report: SignalReport }) {
  const runState = reportRunState(report);
  if (!runState) {
    return (
      <Tooltip>
        <TooltipTrigger
          render={
            <div
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-(--radius-1) bg-(--gray-2) text-(--gray-9) ring-(--gray-4) ring-1 ring-inset"
              role="img"
              aria-label="Report"
            />
          }
        >
          <FileTextIcon size={13} />
        </TooltipTrigger>
        <TooltipContent side="top">Report</TooltipContent>
      </Tooltip>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <div
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ring-1 ring-inset ${runState.orbClass}`}
            role="img"
            aria-label={runState.ariaLabel}
          />
        }
      >
        <span
          className={`block h-1.5 w-1.5 rounded-full ${runState.dotClass}`}
        />
      </TooltipTrigger>
      <TooltipContent side="top">{`Agent ${runState.label.toLowerCase()}`}</TooltipContent>
    </Tooltip>
  );
}

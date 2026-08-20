import { isAgentRunReport } from "@posthog/core/inbox/reportMembership";
import type { SignalReport } from "@posthog/shared/types";
import {
  resolveRunVariant,
  VARIANT_META,
  type VariantMeta,
} from "@posthog/ui/features/inbox/components/AgentRunCard";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";

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
 * The report's leading glyph: a priority monogram once triage stamps one, or a
 * run-state orb (queued / running / failed) while the report is still moving —
 * the same vocabulary the inbox's Runs tab used.
 */
export function ReportStateMonogram({ report }: { report: SignalReport }) {
  const runState = reportRunState(report);
  if (!runState) return <PriorityMonogram priority={report.priority} />;
  return (
    <div
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ring-1 ring-inset ${runState.orbClass}`}
      role="img"
      aria-label={runState.ariaLabel}
      title={runState.label}
    >
      <span className={`block h-1.5 w-1.5 rounded-full ${runState.dotClass}`} />
    </div>
  );
}

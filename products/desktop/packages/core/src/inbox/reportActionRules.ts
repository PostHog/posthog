import type { SignalReport, Task } from "@posthog/shared/domain-types";
import { getTaskPrUrl } from "./reportTasks";

export function isReportAwaitingInput(report: SignalReport): boolean {
  return (
    report.status === "pending_input" ||
    (report.status === "ready" &&
      report.actionability === "requires_human_input")
  );
}

export function canCreateImplementationPr(report: SignalReport): boolean {
  return (
    isReportAwaitingInput(report) ||
    (report.status === "ready" &&
      report.actionability === "immediately_actionable" &&
      report.already_addressed !== true)
  );
}

export function resolveHeaderImplementationPrUrl(
  report: SignalReport,
  implementationTask: Task | null,
): string | null {
  const fromTask = implementationTask ? getTaskPrUrl(implementationTask) : null;
  return fromTask ?? report.implementation_pr_url ?? null;
}

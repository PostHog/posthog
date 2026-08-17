import type { Task, TaskRunStatus } from "@posthog/shared/types";
import type { ReportTaskData } from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { describe, expect, it } from "vitest";
import { buildReportProgress } from "./reportProgress";

function entry(
  id: string,
  purpose: ReportTaskData["purpose"],
  status: TaskRunStatus,
  prUrl?: string,
): ReportTaskData {
  const task = {
    id,
    title: `${purpose} ${id}`,
    latest_run: {
      status,
      output: prUrl ? { pr_url: prUrl } : null,
    },
  } as Task;
  return {
    task,
    purpose,
    purposeLabel: purpose,
    startedAt: `2026-08-10T0${id}:00:00Z`,
  };
}

describe("buildReportProgress", () => {
  it("collapses repeated research runs into one investigation milestone", () => {
    const progress = buildReportProgress([
      entry("1", "research", "completed"),
      entry("2", "research", "completed"),
      entry("3", "research", "completed"),
    ]);

    expect(progress).toEqual([
      expect.objectContaining({
        key: "investigation",
        label: "Investigation",
        description: "Evidence and root cause analysis completed.",
      }),
    ]);
  });

  it("promotes a pull request as the implementation outcome", () => {
    const progress = buildReportProgress([
      entry(
        "1",
        "implementation",
        "completed",
        "https://github.com/example/pr/1",
      ),
    ]);

    expect(progress[0]).toEqual(
      expect.objectContaining({
        label: "Implementation",
        description: "A pull request is ready for review.",
        prUrl: "https://github.com/example/pr/1",
      }),
    );
  });
});

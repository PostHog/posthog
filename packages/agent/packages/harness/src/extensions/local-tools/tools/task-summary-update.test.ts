import { beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";

const setTaskRunSummary = vi.fn();

vi.mock("../signed-commit-artefacts", () => ({
  createSandboxPosthogClient: () => ({ setTaskRunSummary }),
  withReportDeadline: <T>(work: (signal: AbortSignal) => Promise<T>) =>
    work(new AbortController().signal),
}));

import { taskSummaryUpdateTool } from "./task-summary-update";

const ctx = { cwd: "/tmp", taskId: "task-1", taskRunId: "run-1" };

describe("taskSummaryUpdateTool", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setTaskRunSummary.mockResolvedValue({});
  });

  it.each([
    { name: "forwards tags when set", tags: ["feature-flags", "bug-fix"] },
    { name: "leaves tags out when absent", tags: undefined },
  ])("$name", async ({ tags }) => {
    const result = await taskSummaryUpdateTool.handler(ctx, {
      summary: "  Fix the flag.  ",
      tags,
    });
    expect(result.isError).toBeUndefined();
    expect(setTaskRunSummary).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      "Fix the flag.",
      tags,
      expect.any(AbortSignal),
    );
  });

  it.each(["Feature-Flags", "bug_fix", "-lead", "a".repeat(51)])(
    "rejects the invalid tag %s",
    (tag) => {
      const schema = z.object(taskSummaryUpdateTool.schema);
      expect(schema.safeParse({ summary: "s", tags: [tag] }).success).toBe(
        false,
      );
    },
  );
});

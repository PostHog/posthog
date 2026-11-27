import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { TaskToolsApiError } from "../task-tools-client";

const setTaskRunSummary = vi.fn();

vi.mock("../signed-commit-artefacts", async (importActual) => ({
  ...(await importActual<typeof import("../signed-commit-artefacts")>()),
  createSandboxPosthogClient: () => ({ setTaskRunSummary }),
}));

import { taskSummaryUpdateTool } from "./task-summary-update";

const ctx = { cwd: "/tmp", taskId: "task-1", taskRunId: "run-1" };

async function runTool(args: { summary: string; tags?: string[] }) {
  const pending = taskSummaryUpdateTool.handler(ctx, args);
  await vi.runAllTimersAsync();
  return pending;
}

function resultText(result: { content: { type: string; text?: string }[] }) {
  return result.content.map((part) => part.text ?? "").join("");
}

describe("taskSummaryUpdateTool", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    setTaskRunSummary.mockResolvedValue({});
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    { name: "forwards tags when set", tags: ["feature-flags", "bug-fix"] },
    { name: "leaves tags out when absent", tags: undefined },
  ])("$name", async ({ tags }) => {
    const result = await runTool({ summary: "  Fix the flag.  ", tags });
    expect(result.isError).toBeUndefined();
    expect(setTaskRunSummary).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      "Fix the flag.",
      tags,
      expect.any(AbortSignal),
    );
  });

  it.each([
    {
      name: "a server error",
      error: new TaskToolsApiError("Failed request: [500] {}", 500),
    },
    {
      name: "rate limiting",
      error: new TaskToolsApiError("Failed request: [429] {}", 429),
    },
    { name: "a dropped connection", error: new TypeError("fetch failed") },
  ])("retries $name with the same summary and tags", async ({ error }) => {
    setTaskRunSummary.mockRejectedValueOnce(error);
    const result = await runTool({
      summary: "Fix the flag.",
      tags: ["bug-fix"],
    });
    expect(result.isError).toBeUndefined();
    expect(setTaskRunSummary).toHaveBeenCalledTimes(2);
    expect(setTaskRunSummary.mock.calls[1].slice(0, 4)).toEqual(
      setTaskRunSummary.mock.calls[0].slice(0, 4),
    );
  });

  it("does not retry a summary the server rejects", async () => {
    setTaskRunSummary.mockRejectedValue(
      new TaskToolsApiError('Failed request: [400] {"tags":["bad"]}', 400),
    );
    const result = await runTool({ summary: "Fix the flag." });
    expect(result.isError).toBe(true);
    expect(setTaskRunSummary).toHaveBeenCalledTimes(1);
    expect(resultText(result)).toContain("rejected the summary");
  });

  it.each([
    {
      name: "keeps failing",
      fail: () =>
        Promise.reject(new TaskToolsApiError("Failed request: [500] {}", 500)),
    },
    { name: "never answers", fail: () => new Promise(() => {}) },
  ])("stops within the deadline when the server $name", async ({ fail }) => {
    setTaskRunSummary.mockImplementation(fail);
    const startedAt = Date.now();
    const result = await runTool({ summary: "Fix the flag." });
    expect(result.isError).toBe(true);
    expect(setTaskRunSummary).toHaveBeenCalledTimes(3);
    expect(Date.now() - startedAt).toBeLessThanOrEqual(30_000);
    expect(resultText(result)).toContain("may not be saved");
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

import { beforeEach, describe, expect, it, vi } from "vitest";

const notifyTaskOwner = vi.fn();

vi.mock("../signed-commit-artefacts", () => ({
  createSandboxPosthogClient: () => ({ notifyTaskOwner }),
  withReportDeadline: <T>(work: (signal: AbortSignal) => Promise<T>) =>
    work(new AbortController().signal),
}));

import { enabledLocalTools } from "../index";
import type { LocalToolGateMeta } from "../registry";
import { notifyUserTool } from "./notify-user";

const ctx = { cwd: "/repo", taskId: "task-1", taskRunId: "run-1" };

describe("notify_user tool", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    { meta: { environment: "cloud", notifyUser: true }, expected: true },
    { meta: { environment: "cloud" }, expected: false },
    { meta: { environment: "local", notifyUser: true }, expected: false },
  ] as { meta: LocalToolGateMeta; expected: boolean }[])(
    "gate: $meta → $expected",
    ({ meta, expected }) => {
      const names = enabledLocalTools(ctx, meta).map((tool) => tool.name);
      expect(names.includes(notifyUserTool.name)).toBe(expected);
    },
  );

  it.each([
    { result: "sent", isError: undefined },
    { result: "throttled", isError: true },
    { result: "not_sent", isError: true },
  ])("reports a $result result to the agent", async ({ result, isError }) => {
    notifyTaskOwner.mockResolvedValue({
      result,
      detail: `detail for ${result}`,
      replies_continue_task: false,
    });

    const output = await notifyUserTool.handler(ctx, {
      channel: "slack",
      reason: "needs_input",
      message: "  Which region should I deploy to?  ",
    });

    expect(output.isError).toBe(isError);
    expect(output.content[0].text).toBe(`detail for ${result}`);
    expect(notifyTaskOwner).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      {
        channel: "slack",
        reason: "needs_input",
        message: "Which region should I deploy to?",
      },
      expect.any(AbortSignal),
    );
  });
});

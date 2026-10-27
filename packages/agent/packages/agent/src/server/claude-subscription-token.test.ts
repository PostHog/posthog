import { afterEach, describe, expect, it, vi } from "vitest";
import { ClaudeSubscriptionTokenError } from "../posthog-api";
import { ClaudeSubscriptionTokenClient } from "./claude-subscription-token";

afterEach(() => vi.useRealTimers());

describe("Claude token rejection reports", () => {
  it.each([
    {
      transientFailures: 0,
      terminalCode: "reauth_required",
      terminalStatus: 409,
      expectedAttempts: 1,
    },
    {
      transientFailures: 1,
      terminalCode: "reauth_required",
      terminalStatus: 409,
      expectedAttempts: 2,
    },
    {
      transientFailures: 2,
      terminalCode: "reauth_required",
      terminalStatus: 409,
      expectedAttempts: 3,
    },
    {
      transientFailures: 3,
      terminalCode: "request_failed",
      terminalStatus: 503,
      expectedAttempts: 3,
    },
    {
      transientFailures: 0,
      terminalCode: "forbidden",
      terminalStatus: 403,
      expectedAttempts: 1,
    },
    {
      transientFailures: 0,
      terminalCode: "request_failed",
      terminalStatus: 400,
      expectedAttempts: 1,
    },
  ] as const)(
    "settles after $expectedAttempts attempts with $transientFailures transient failures",
    async ({
      transientFailures,
      terminalCode,
      terminalStatus,
      expectedAttempts,
    }) => {
      vi.useFakeTimers();
      let attempts = 0;
      const requestClaudeSubscriptionToken = vi.fn(
        async (): Promise<string> => {
          attempts += 1;
          const code =
            attempts <= transientFailures ? "request_failed" : terminalCode;
          throw new ClaudeSubscriptionTokenError(
            code,
            attempts <= transientFailures ? 503 : terminalStatus,
            "Test response",
          );
        },
      );
      const client = new ClaudeSubscriptionTokenClient({
        posthogAPI: { requestClaudeSubscriptionToken },
        taskId: "task-1",
        runId: "run-1",
        runToken: "fake-run-token",
      });
      const report = client.reportRejected("fake-claude-token");
      expect(client.reportRejected("fake-claude-token")).toBe(report);
      await vi.runAllTimersAsync();
      await report;
      expect(requestClaudeSubscriptionToken).toHaveBeenCalledTimes(
        expectedAttempts,
      );
    },
  );
});

import { describe, expect, it } from "vitest";
import {
  isMethod,
  isNotification,
  POSTHOG_METHODS,
  POSTHOG_NOTIFICATIONS,
  withTurnTraceId,
} from "./acp-extensions";

describe("isNotification", () => {
  it("matches the exact notification name", () => {
    expect(
      isNotification(
        POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
        POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
      ),
    ).toBe(true);
  });

  it("matches the double-underscore prefix variant", () => {
    expect(
      isNotification(
        `_${POSTHOG_NOTIFICATIONS.TURN_COMPLETE}`,
        POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
      ),
    ).toBe(true);
  });

  it("returns false for a different notification", () => {
    expect(
      isNotification(
        POSTHOG_NOTIFICATIONS.USAGE_UPDATE,
        POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
      ),
    ).toBe(false);
  });

  it("returns false for undefined", () => {
    expect(isNotification(undefined, POSTHOG_NOTIFICATIONS.TURN_COMPLETE)).toBe(
      false,
    );
  });
});

describe("isMethod", () => {
  it("matches the exact method name", () => {
    expect(
      isMethod(
        POSTHOG_METHODS.REFRESH_SESSION,
        POSTHOG_METHODS.REFRESH_SESSION,
      ),
    ).toBe(true);
  });

  it("matches the double-underscore prefix variant", () => {
    expect(
      isMethod(
        `_${POSTHOG_METHODS.REFRESH_SESSION}`,
        POSTHOG_METHODS.REFRESH_SESSION,
      ),
    ).toBe(true);
  });

  it("returns false for unrelated method strings", () => {
    expect(isMethod("session/prompt", POSTHOG_METHODS.REFRESH_SESSION)).toBe(
      false,
    );
  });

  it("returns false for undefined", () => {
    expect(isMethod(undefined, POSTHOG_METHODS.REFRESH_SESSION)).toBe(false);
  });
});

describe("withTurnTraceId", () => {
  // A codex turn reports no trace id of its own, so the stamped run id is the
  // only thing a rating on it can open.
  it.each([
    [
      "names the stamped run on a turn that reports none",
      { params: { sessionId: "s", stopReason: "end_turn" } },
      "run-1",
      "run-1",
    ],
    [
      "keeps the trace id the adapter reported",
      { params: { sessionId: "s", traceId: "trace-abc" } },
      "run-1",
      "trace-abc",
    ],
    [
      "names nothing when no header stamped the run",
      { params: { sessionId: "s" } },
      null,
      undefined,
    ],
  ])("%s", (_name, message, stamped, expected) => {
    const result = withTurnTraceId(
      {
        jsonrpc: "2.0",
        method: POSTHOG_NOTIFICATIONS.TURN_COMPLETE,
        ...message,
      },
      stamped,
    ) as { params: { traceId?: string; sessionId: string } };

    expect(result.params.traceId).toBe(expected);
    expect(result.params.sessionId).toBe("s");
  });

  it("leaves a notification of another kind alone", () => {
    const message = {
      jsonrpc: "2.0",
      method: POSTHOG_NOTIFICATIONS.TASK_COMPLETE,
      params: { sessionId: "s" },
    };

    expect(withTurnTraceId(message, "run-1")).toBe(message);
  });
});

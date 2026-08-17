import type { AgentSession } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";

const RUN_ID = "run-1";

interface Handlers {
  onData: (payload: unknown) => void;
  onError?: (err: unknown) => void;
  onComplete?: () => void;
}

/** Mirrors the ipc link: tearing a subscription down completes its observer. */
function fakeSubscription() {
  const subscriptions: { handlers: Handlers; unsubscribe: () => void }[] = [];
  return {
    subscriptions,
    subscribe: vi.fn((_input: unknown, handlers: Handlers) => {
      const unsubscribe = vi.fn(() => handlers.onComplete?.());
      subscriptions.push({ handlers, unsubscribe });
      return { unsubscribe };
    }),
  };
}

function createHarness() {
  const sessions: Record<string, AgentSession> = {
    [RUN_ID]: {
      taskRunId: RUN_ID,
      taskId: "task-1",
      taskTitle: "Local Task",
      events: [],
      messageQueue: [],
      pendingPermissions: new Map(),
      status: "connected",
    } as unknown as AgentSession,
  };
  const events = fakeSubscription();
  const permissions = fakeSubscription();
  const log = { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() };
  const deps = {
    store: {
      getSessions: () => sessions,
      getSessionByTaskId: (taskId: string) =>
        Object.values(sessions).find((s) => s.taskId === taskId),
      updateSession: vi.fn(),
    },
    log,
    trpc: {
      agent: {
        onSessionEvent: { subscribe: events.subscribe },
        onPermissionRequest: { subscribe: permissions.subscribe },
        onSessionIdleKilled: { subscribe: () => ({ unsubscribe: vi.fn() }) },
      },
    },
  } as unknown as SessionServiceDeps;
  const service = new SessionService(deps);
  (
    service as unknown as { subscribeToChannel(taskRunId: string): void }
  ).subscribeToChannel(RUN_ID);
  return { service, events, permissions, log };
}

describe("session subscription lifecycle", () => {
  it("resubscribes when the host ends a subscription without an error", () => {
    const { events, permissions, log } = createHarness();

    events.subscriptions[0].handlers.onComplete?.();

    expect(events.subscribe).toHaveBeenCalledTimes(2);
    expect(permissions.subscribe).toHaveBeenCalledTimes(2);
    expect(permissions.subscriptions[0].unsubscribe).toHaveBeenCalledTimes(1);
    expect(log.warn).toHaveBeenCalledWith(
      "Session subscription ended without an error, resubscribing",
      { taskRunId: RUN_ID, which: "event", attempts: 1 },
    );
  });

  it("stops resubscribing when the host keeps ending the subscription", () => {
    const { events, log } = createHarness();

    for (let i = 0; i < 5; i++) {
      events.subscriptions.at(-1)?.handlers.onComplete?.();
    }

    expect(events.subscribe).toHaveBeenCalledTimes(4);
    expect(log.error).toHaveBeenCalledWith(
      "Session subscription keeps ending without an error, giving up",
      { taskRunId: RUN_ID, which: "event", attempts: 4 },
    );
  });

  it("forgets earlier resubscribes once events flow again", () => {
    vi.useFakeTimers();
    try {
      const { events, log } = createHarness();

      for (let i = 0; i < 3; i++) {
        events.subscriptions.at(-1)?.handlers.onComplete?.();
      }
      events.subscriptions.at(-1)?.handlers.onData({
        type: "acp_message",
        ts: 1,
        message: { jsonrpc: "2.0", method: "session/update", params: {} },
      });
      events.subscriptions.at(-1)?.handlers.onComplete?.();

      expect(events.subscribe).toHaveBeenCalledTimes(5);
      expect(log.error).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not resubscribe when the service tears the channel down itself", () => {
    const { service, events, permissions, log } = createHarness();

    service.reset();

    expect(events.subscriptions[0].unsubscribe).toHaveBeenCalledTimes(1);
    expect(events.subscribe).toHaveBeenCalledTimes(1);
    expect(permissions.subscribe).toHaveBeenCalledTimes(1);
    expect(log.warn).not.toHaveBeenCalled();
  });
});

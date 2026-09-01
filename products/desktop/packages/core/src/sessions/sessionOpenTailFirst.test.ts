import { afterEach, describe, expect, it, vi } from "vitest";
import { SessionService, type SessionServiceDeps } from "./sessionService";
import { sessionStore, sessionStoreSetters } from "./sessionStore";

const RUN = "run-tf";
const TASK = "task-tf";

function line(text: string): string {
  return JSON.stringify({
    type: "notification",
    notification: {
      method: "session/update",
      params: {
        update: {
          sessionUpdate: "agent_message_chunk",
          content: { type: "text", text },
        },
      },
    },
  });
}

function makeService(readTail?: unknown) {
  const logs: Record<string, unknown> = {
    readLocalLogs: { query: vi.fn().mockResolvedValue(null) },
    fetchS3Logs: { query: vi.fn().mockResolvedValue(null) },
    writeLocalLogs: { mutate: vi.fn() },
  };
  if (readTail !== undefined) logs.readLocalLogsTail = { query: readTail };

  const deps = {
    store: sessionStoreSetters,
    log: { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() },
    notifyPromptComplete: vi.fn(),
    notifyPermissionRequest: vi.fn(),
    taskViewedApi: { markActivity: vi.fn() },
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions: vi.fn(),
    trpc: {
      agent: {
        onSessionEvent: { subscribe: () => ({ unsubscribe: vi.fn() }) },
        onPermissionRequest: { subscribe: () => ({ unsubscribe: vi.fn() }) },
        onSessionIdleKilled: { subscribe: () => ({ unsubscribe: vi.fn() }) },
      },
      logs,
    },
  } as unknown as SessionServiceDeps;
  return new SessionService(deps);
}

type Painter = {
  paintTailFirst(r: string, t: string, ti: string, u: string): Promise<void>;
};
const paint = (svc: SessionService) =>
  (svc as unknown as Painter).paintTailFirst(RUN, TASK, "Title", "log-url");

const events = () => sessionStore.getState().sessions[RUN]?.events ?? [];

afterEach(() => sessionStoreSetters.removeSession(RUN));

describe("paintTailFirst", () => {
  it("paints a session from the tail content", async () => {
    const readTail = vi.fn().mockResolvedValue({
      content: `${line("a")}\n${line("b")}\n`,
      truncated: true,
    });
    await paint(makeService(readTail));

    expect(readTail).toHaveBeenCalledWith({
      taskRunId: RUN,
      maxBytes: 1_500_000,
    });
    expect(events().length).toBeGreaterThan(0);
    expect(sessionStore.getState().sessions[RUN]?.logUrl).toBe("log-url");
  });

  it("is a no-op when the host doesn't expose the tail read", async () => {
    await paint(makeService(undefined));
    expect(sessionStore.getState().sessions[RUN]).toBeUndefined();
  });

  it("is a no-op when a session already exists", async () => {
    const readTail = vi
      .fn()
      .mockResolvedValue({ content: line("x"), truncated: true });
    sessionStoreSetters.setSession({
      taskRunId: RUN,
      taskId: TASK,
      events: [],
      messageQueue: [],
      pendingPermissions: new Map(),
      status: "connected",
    } as never);
    await paint(makeService(readTail));
    expect(readTail).not.toHaveBeenCalled();
  });

  it("is a no-op on empty tail content", async () => {
    const readTail = vi
      .fn()
      .mockResolvedValue({ content: "  ", truncated: true });
    await paint(makeService(readTail));
    expect(sessionStore.getState().sessions[RUN]).toBeUndefined();
  });
});

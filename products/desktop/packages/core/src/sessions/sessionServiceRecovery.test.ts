import type { AgentSession, StoredLogEntry } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  type ReconcileTaskConnectionParams,
  SessionService,
  type SessionServiceDeps,
} from "./sessionService";

const IN_FLIGHT_TTL_MS = 10 * 60 * 1000;

function makeSession(taskId: string): AgentSession {
  return {
    taskRunId: `run-${taskId}`,
    taskId,
    taskTitle: taskId,
    channel: "",
    events: [],
    startedAt: 1,
    status: "connected",
    isPromptPending: false,
    isCompacting: false,
    promptStartedAt: null,
    pendingPermissions: new Map(),
    pausedDurationMs: 0,
    messageQueue: [],
    optimisticItems: [],
  } as AgentSession;
}

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    title: "Test task",
    description: "Ship the fix",
    latest_run: null,
    ...overrides,
  } as Task;
}

function createHarness({ spyConnect = true } = {}) {
  const sessions: Record<string, AgentSession> = {};
  const store = {
    getSessions: () => sessions,
    getSessionByTaskId: (taskId: string) =>
      Object.values(sessions).find((s) => s.taskId === taskId),
    setSession: (session: AgentSession) => {
      sessions[session.taskRunId] = session;
    },
    removeSession: vi.fn(),
    setTaskStarting: vi.fn(),
    clearTaskStarting: vi.fn(),
    updateSession: vi.fn(
      (taskRunId: string, updates: Partial<AgentSession>) => {
        Object.assign(sessions[taskRunId], updates);
      },
    ),
  };
  const log = { info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() };
  const deps = {
    store,
    log,
    getPersistedConfigOptions: () => undefined,
    setPersistedConfigOptions: vi.fn(),
    removePersistedConfigOptions: vi.fn(),
    adapterStore: {
      getAdapter: () => undefined,
      setAdapter: vi.fn(),
      removeAdapter: vi.fn(),
    },
    trpc: {
      agent: {
        cancel: { mutate: vi.fn().mockResolvedValue(undefined) },
        reconnect: { mutate: vi.fn().mockResolvedValue({}) },
        onSessionEvent: { subscribe: () => ({ unsubscribe: vi.fn() }) },
        onPermissionRequest: { subscribe: () => ({ unsubscribe: vi.fn() }) },
        onSessionIdleKilled: {
          subscribe: () => ({ unsubscribe: vi.fn() }),
        },
      },
      workspace: {
        verify: { query: vi.fn().mockResolvedValue({ exists: true }) },
      },
    },
    settings: {},
    track: vi.fn(),
  } as unknown as SessionServiceDeps;

  const service = new SessionService(deps);
  const connectToTask = spyConnect
    ? vi.spyOn(service, "connectToTask").mockResolvedValue(undefined)
    : undefined;
  return { service, sessions, connectToTask, log, store };
}

function reconcile(
  service: SessionService,
  task: Task,
  session?: AgentSession,
): () => void {
  return service.reconcileTaskConnection({
    task,
    session,
    repoPath: "/repo",
    isCloud: false,
    isOnline: true,
    cloudAuth: { status: "loading" },
  } as ReconcileTaskConnectionParams);
}

describe("SessionService run-less local task recovery", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    {
      case: "sends the description as the initial prompt",
      description: "Ship the fix",
      initialPrompt: [{ type: "text", text: "Ship the fix" }],
    },
    {
      case: "connects without a prompt when the description is empty",
      description: "",
      initialPrompt: undefined,
    },
  ])("starts a first run and $case", ({ description, initialPrompt }) => {
    const { service, connectToTask } = createHarness();
    const task = makeTask({ description });

    reconcile(service, task);

    const expected: Record<string, unknown> = { task, repoPath: "/repo" };
    if (initialPrompt) {
      expected.initialPrompt = initialPrompt;
    }
    expect(connectToTask).toHaveBeenCalledWith(expected);
  });

  it("recovers a run-less task whose session is disconnected", () => {
    const { service, connectToTask } = createHarness();
    const task = makeTask();
    const session = {
      ...makeSession(task.id),
      status: "disconnected" as const,
    };

    reconcile(service, task, session);

    expect(connectToTask).toHaveBeenCalledWith({
      task,
      repoPath: "/repo",
      initialPrompt: [{ type: "text", text: "Ship the fix" }],
    });
  });

  it("does not recover while a session is connecting", () => {
    const { service, connectToTask } = createHarness();
    const task = makeTask();
    const session = { ...makeSession(task.id), status: "connecting" as const };

    reconcile(service, task, session);

    expect(connectToTask).not.toHaveBeenCalled();
  });

  it("defers to an in-flight creation and recovers once the mark expires", () => {
    vi.useFakeTimers();
    vi.setSystemTime(0);
    const { service, connectToTask } = createHarness();
    const task = makeTask();

    service.markTaskCreationInFlight(task.id);
    reconcile(service, task);
    expect(connectToTask).not.toHaveBeenCalled();

    vi.setSystemTime(IN_FLIGHT_TTL_MS + 1);
    reconcile(service, task);
    expect(connectToTask).toHaveBeenCalledTimes(1);
  });

  it("keeps the starting marker while clearing the recovery in-flight mark", async () => {
    const { service, sessions, store } = createHarness({ spyConnect: false });
    const task = makeTask();
    sessions[`run-${task.id}`] = {
      ...makeSession(task.id),
      status: "connecting",
    };
    service.markTaskCreationInFlight(task.id);
    vi.mocked(store.setTaskStarting).mockClear();
    vi.mocked(store.clearTaskStarting).mockClear();

    await service.connectToTask({ task, repoPath: "/repo" });

    expect(store.setTaskStarting).toHaveBeenCalledWith(task.id, undefined);
    expect(store.clearTaskStarting).not.toHaveBeenCalled();

    const connectToTask = vi
      .spyOn(service, "connectToTask")
      .mockResolvedValue(undefined);
    reconcile(service, task);
    expect(connectToTask).toHaveBeenCalledTimes(1);
  });

  it("resumes an existing run without injecting a prompt", () => {
    const { service, connectToTask } = createHarness();
    const task = makeTask({
      latest_run: { id: "run-9" } as Task["latest_run"],
    });

    reconcile(service, task);

    expect(connectToTask).toHaveBeenCalledWith({ task, repoPath: "/repo" });
  });

  it("clears stale pending state when the reconnected log contains a completed turn", async () => {
    const { service, sessions } = createHarness({ spyConnect: false });
    const task = makeTask();
    sessions["run-task-1"] = {
      ...makeSession(task.id),
      isPromptPending: true,
      promptStartedAt: 1,
      currentPromptId: 1,
    };
    const rawEntries: StoredLogEntry[] = [
      {
        type: "notification",
        timestamp: new Date(1).toISOString(),
        notification: {
          id: 1,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "Ship the fix" }] },
        },
      },
      {
        type: "notification",
        timestamp: new Date(2).toISOString(),
        notification: {
          id: 1,
          result: { stopReason: "end_turn" },
        },
      },
    ];

    await (
      service as unknown as {
        reconnectToLocalSession: (
          taskId: string,
          taskRunId: string,
          taskTitle: string,
          logUrl: string | undefined,
          repoPath: string,
          auth: { apiHost: string; projectId: number },
          prefetchedLogs: { rawEntries: StoredLogEntry[] },
        ) => Promise<boolean>;
      }
    ).reconnectToLocalSession(
      task.id,
      "run-task-1",
      task.title,
      undefined,
      "/repo",
      {
        apiHost: "https://example.com",
        projectId: 1,
      },
      { rawEntries },
    );

    expect(sessions["run-task-1"]).toMatchObject({
      isPromptPending: false,
      promptStartedAt: null,
      currentPromptId: null,
    });
  });
});

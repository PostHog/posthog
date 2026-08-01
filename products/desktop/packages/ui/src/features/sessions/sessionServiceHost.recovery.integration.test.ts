/**
 * End-to-end recovery test against the REAL Zustand session store.
 *
 * This test exercises the actual store so the
 * `updateSession -> getSessionByTaskId -> drain` chain is real — the precise
 * interaction the unit tests stub out. It deterministically reproduces a
 * resumed cloud run that goes idle, an SSE transport drop flips the session to `disconnected`, a
 * user message is queued, and nothing ever drains it.
 *
 * Only the tRPC network boundary is faked, that boundary is the thing we simulate dropping.
 */
import type { ContentBlock } from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockTrpcAgent = vi.hoisted(() => ({
  start: { mutate: vi.fn() },
  reconnect: { mutate: vi.fn() },
  cancel: { mutate: vi.fn() },
  prompt: { mutate: vi.fn() },
  cancelPrompt: { mutate: vi.fn() },
  setConfigOption: { mutate: vi.fn() },
  respondToPermission: { mutate: vi.fn() },
  cancelPermission: { mutate: vi.fn() },
  onSessionEvent: { subscribe: vi.fn() },
  onPermissionRequest: { subscribe: vi.fn() },
  onSessionIdleKilled: { subscribe: vi.fn(() => ({ unsubscribe: vi.fn() })) },
  resetAll: { mutate: vi.fn().mockResolvedValue(undefined) },
  getPreviewConfigOptions: { query: vi.fn().mockResolvedValue([]) },
}));

const mockTrpcWorkspace = vi.hoisted(() => ({
  verify: { query: vi.fn() },
}));

const mockTrpcLogs = vi.hoisted(() => ({
  fetchS3Logs: { query: vi.fn() },
  readLocalLogs: { query: vi.fn() },
  writeLocalLogs: { mutate: vi.fn() },
}));

const mockTrpcCloudTask = vi.hoisted(() => ({
  sendCommand: { mutate: vi.fn() },
  watch: { mutate: vi.fn().mockResolvedValue(undefined) },
  retry: { mutate: vi.fn().mockResolvedValue(undefined) },
  unwatch: { mutate: vi.fn().mockResolvedValue(undefined) },
  onUpdate: { subscribe: vi.fn() },
}));

const mockTrpcFs = vi.hoisted(() => ({
  readFileAsBase64: { query: vi.fn() },
}));

const mockTrpcHandoff = vi.hoisted(() => ({
  preflightToCloud: { query: vi.fn() },
  executeToCloud: { mutate: vi.fn() },
}));

const mockTrpcOs = vi.hoisted(() => ({
  openExternal: { mutate: vi.fn() },
}));

const mockAuthenticatedClient = vi.hoisted(() => ({
  createTaskRun: vi.fn(),
  appendTaskRunLog: vi.fn(),
  getTaskRun: vi.fn(),
  getTask: vi.fn(),
  runTaskInCloud: vi.fn(),
  prepareTaskRunArtifactUploads: vi.fn(),
  finalizeTaskRunArtifactUploads: vi.fn(),
  prepareTaskStagedArtifactUploads: vi.fn(),
  finalizeTaskStagedArtifactUploads: vi.fn(),
  startGithubUserIntegrationConnect: vi.fn(),
}));

type MockAuthenticatedClient = typeof mockAuthenticatedClient;

const mockBuildAuthenticatedClient = vi.hoisted(() =>
  vi.fn<() => MockAuthenticatedClient | null>(() => mockAuthenticatedClient),
);

const mockAuth = vi.hoisted(() => ({
  fetchAuthState: vi.fn<() => Promise<Record<string, unknown>>>(async () => ({
    status: "authenticated",
    bootstrapComplete: true,
    cloudRegion: "us",
    orgProjectsMap: {
      "org-1": {
        orgName: "Org 1",
        projects: [{ id: 123, name: "Project 123" }],
      },
    },
    currentOrgId: "org-1",
    currentProjectId: 123,
    hasCodeAccess: true,
    needsScopeReauth: false,
  })),
  getAuthenticatedClient: vi.fn<() => Promise<Record<string, unknown> | null>>(
    async () => mockBuildAuthenticatedClient(),
  ),
  createAuthenticatedClient: vi.fn((authState: Record<string, unknown>) => {
    return authState.status === "authenticated"
      ? mockBuildAuthenticatedClient()
      : null;
  }),
}));

vi.mock("@posthog/ui/features/auth/authQueries", () => ({
  AUTH_SCOPED_QUERY_META: { authScoped: true },
  clearAuthScopedQueries: vi.fn(),
  getAuthIdentity: vi.fn(),
  fetchAuthState: mockAuth.fetchAuthState,
}));
vi.mock("@posthog/ui/features/auth/authClientImperative", () => ({
  getAuthenticatedClient: mockAuth.getAuthenticatedClient,
  createAuthenticatedClient: mockAuth.createAuthenticatedClient,
}));

vi.mock("@features/sessions/stores/modelsStore", () => ({
  useModelsStore: {
    getState: () => ({
      getEffectiveModel: () => "claude-3-opus",
    }),
  },
}));

const mockSessionConfigStore = vi.hoisted(() => ({
  getPersistedConfigOptions: vi.fn(() => undefined),
  setPersistedConfigOptions: vi.fn(),
  removePersistedConfigOptions: vi.fn(),
}));

vi.mock(
  "@posthog/ui/features/sessions/sessionConfigStore",
  () => mockSessionConfigStore,
);

const mockAdapterFns = vi.hoisted(() => ({
  setAdapter: vi.fn(),
  getAdapter: vi.fn(),
  removeAdapter: vi.fn(),
}));

const mockSessionAdapterStore = vi.hoisted(() => ({
  useSessionAdapterStore: {
    getState: vi.fn(() => ({
      adaptersByRunId: {},
      ...mockAdapterFns,
    })),
  },
}));

vi.mock(
  "@posthog/ui/features/sessions/sessionAdapterStore",
  () => mockSessionAdapterStore,
);

const mockGetIsOnline = vi.hoisted(() => vi.fn(() => true));

vi.mock("@posthog/core/connectivity/connectivityStore", () => ({
  getIsOnline: () => mockGetIsOnline(),
}));

const mockNotificationService = vi.hoisted(() => ({
  notifyPermissionRequest: vi.fn(),
  notifyPromptComplete: vi.fn(),
}));

vi.mock("@posthog/di/container", () => ({
  resolveService: (token: unknown) => {
    if (token === Symbol.for("posthog.host.trpcClient")) {
      return {
        agent: mockTrpcAgent,
        workspace: mockTrpcWorkspace,
        logs: mockTrpcLogs,
        cloudTask: mockTrpcCloudTask,
        fs: mockTrpcFs,
        handoff: mockTrpcHandoff,
        os: mockTrpcOs,
      };
    }
    if (token === Symbol.for("posthog.ui.ImperativeQueryClient")) {
      return {
        invalidateQueries: vi.fn(),
        refetchQueries: vi.fn(),
        setQueriesData: vi.fn(),
      };
    }
    if (typeof token === "function" && token.name === "NotificationBus") {
      return mockNotificationService;
    }
    throw new Error(`resolveService: unmocked token ${String(token)}`);
  },
}));

const mockSettingsState = vi.hoisted(() => ({
  customInstructions: "",
}));

vi.mock(
  "@posthog/ui/features/settings/settingsStore",
  async (importOriginal) => ({
    ...(await importOriginal<
      typeof import("@posthog/ui/features/settings/settingsStore")
    >()),
    useSettingsStore: {
      getState: () => mockSettingsState,
    },
  }),
);

vi.mock("@posthog/ui/features/sidebar/taskMetaApi", () => ({
  taskViewedApi: {
    markActivity: vi.fn(),
    markAsViewed: vi.fn(),
  },
}));

vi.mock("@posthog/ui/shell/posthogAnalyticsImpl", () => ({
  track: vi.fn(),
  buildPermissionToolMetadata: vi.fn(() => ({})),
  posthogFeatureFlags: {
    isEnabled: vi.fn(() => undefined),
    onFlagsLoaded: vi.fn(),
  },
}));
vi.mock("../../shell/logger", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: vi.fn(), info: vi.fn() },
}));
vi.mock("@posthog/shared", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@posthog/shared")>()),
  getCloudUrlFromRegion: () => "https://api.anthropic.com",
}));

const mockConvertStoredEntriesToEvents = vi.hoisted(() =>
  vi.fn<(entries: unknown[]) => unknown[]>(() => []),
);

vi.mock("@posthog/core/sessions/sessionEvents", async () => {
  const actual = await vi.importActual<
    typeof import("@posthog/core/sessions/sessionEvents")
  >("@posthog/core/sessions/sessionEvents");
  return {
    ...actual,
    convertStoredEntriesToEvents: mockConvertStoredEntriesToEvents,
    createUserPromptEvent: vi.fn((prompt, ts) => ({
      type: "acp_message",
      ts,
      message: {
        jsonrpc: "2.0",
        id: ts,
        method: "session/prompt",
        params: { prompt },
      },
    })),
    createUserMessageEvent: vi.fn((message, ts) => ({
      type: "user",
      ts,
      message,
    })),
    createUserShellExecuteEvent: vi.fn(() => ({
      type: "acp_message",
      ts: Date.now(),
      message: {},
    })),
    extractPromptText: vi.fn((p) => (typeof p === "string" ? p : "text")),
    getUserShellExecutesSinceLastPrompt: vi.fn(() => []),
    isFatalSessionError: actual.isFatalSessionError,
    isRateLimitError: actual.isRateLimitError,
    normalizePromptToBlocks: vi.fn((p) =>
      typeof p === "string" ? [{ type: "text", text: p }] : p,
    ),
    shellExecutesToContextBlocks: vi.fn(() => []),
  };
});

// NOTE: deliberately NOT mocking "@posthog/ui/features/sessions/sessionStore" —
// the real Zustand store is the whole point of this test.
import type { AgentSession } from "@posthog/ui/features/sessions/sessionStore";
import {
  sessionStoreSetters,
  useSessionStore,
} from "@posthog/ui/features/sessions/sessionStore";
import { getSessionService, resetSessionService } from "./sessionServiceHost";

const TASK_ID = "task-299bc88e";
const RUN_ID = "run-6f83616d";

type CloudUpdateOnData = (update: Record<string, unknown>) => void;

function latestOnData(): CloudUpdateOnData {
  const calls = mockTrpcCloudTask.onUpdate.subscribe.mock.calls;
  const last = calls.at(-1);
  if (!last) throw new Error("watchCloudTask did not subscribe to onUpdate");
  return (last[1] as { onData: CloudUpdateOnData }).onData;
}

function makeBaseSession(overrides: Partial<AgentSession>): AgentSession {
  return {
    taskRunId: RUN_ID,
    taskId: TASK_ID,
    taskTitle: "Idle queued-up messages",
    channel: `agent-event:${RUN_ID}`,
    events: [],
    startedAt: Date.now(),
    status: "connecting",
    isPromptPending: false,
    isCompacting: false,
    promptStartedAt: null,
    pendingPermissions: new Map(),
    pausedDurationMs: 0,
    messageQueue: [],
    optimisticItems: [],
    isCloud: true,
    cloudStatus: "in_progress",
    processedLineCount: 0,
    ...overrides,
  };
}

describe("SessionService cloud queue recovery (real store, e2e)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useSessionStore.setState({ sessions: {}, taskIdIndex: {} });
    mockConvertStoredEntriesToEvents.mockImplementation(() => []);
    resetSessionService();
    mockSettingsState.customInstructions = "";
    mockGetIsOnline.mockReturnValue(true);
    mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
    mockAuth.fetchAuthState.mockResolvedValue({
      status: "authenticated",
      bootstrapComplete: true,
      cloudRegion: "us",
      orgProjectsMap: {
        "org-1": {
          orgName: "Org 1",
          projects: [{ id: 123, name: "Project 123" }],
        },
      },
      currentOrgId: "org-1",
      currentProjectId: 123,
      hasCodeAccess: true,
      needsScopeReauth: false,
    });
    mockTrpcAgent.onSessionEvent.subscribe.mockReturnValue({
      unsubscribe: vi.fn(),
    });
    mockTrpcAgent.onPermissionRequest.subscribe.mockReturnValue({
      unsubscribe: vi.fn(),
    });
    mockTrpcCloudTask.onUpdate.subscribe.mockReturnValue({
      unsubscribe: vi.fn(),
    });
    mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
    mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
    mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);
    mockTrpcFs.readFileAsBase64.query.mockResolvedValue(null);
    mockAuthenticatedClient.prepareTaskRunArtifactUploads.mockResolvedValue([]);
    mockAuthenticatedClient.finalizeTaskRunArtifactUploads.mockResolvedValue(
      [],
    );
    mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
      success: true,
      result: { stopReason: "end_turn" },
    });
  });

  it("recovers a stranded queue after an idle resumed run drops to disconnected", async () => {
    const service = getSessionService();

    // Subscribe (captures the onUpdate.onData channel) without letting the
    // async hydrate clobber the state we control below.
    service.watchCloudTask(
      TASK_ID,
      RUN_ID,
      "https://api.anthropic.com",
      123,
      undefined,
      "https://logs.example.com/run",
    );
    const onData = latestOnData();

    // Start: agent booting, not yet ready (mirrors a snapshot-resume run
    // before its run_started/turn_complete reaches the renderer).
    sessionStoreSetters.setSession(makeBaseSession({ status: "disconnected" }));

    // --- Phase A: the agent's resume turn completes -------------------------
    // The real _posthog/turn_complete handler must flip the session to
    // "connected" AND record agentIdleForRunId for this exact run.
    const turnCompleteEvent = {
      type: "acp_message" as const,
      ts: Date.now(),
      message: {
        jsonrpc: "2.0" as const,
        method: "_posthog/turn_complete",
        params: { sessionId: "acp-session", stopReason: "end_turn" },
      },
    };
    mockConvertStoredEntriesToEvents.mockReturnValueOnce([turnCompleteEvent]);
    onData({
      kind: "snapshot",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
      newEntries: [{ notification: { method: "_posthog/turn_complete" } }],
      totalEntryCount: 1,
    });

    await vi.waitFor(() => {
      const s = useSessionStore.getState().sessions[RUN_ID];
      expect(s?.status).toBe("connected");
      expect(s?.agentIdleForRunId).toBe(RUN_ID);
    });

    // --- Phase B: SSE transport drop, then the user sends a message --------
    // retryCloudTaskWatch() flips the session to "disconnected" (api.py-side
    // run is still alive/in_progress). The user's message gets queued
    // because status !== "connected" — exactly the production deadlock.
    //
    // Keep the queue-gate's retry in-flight (never resolves) so the
    // post-retry recovery (trigger #2) cannot pre-empt this case. This test
    // isolates the status-update-driven recovery (trigger #1) below.
    mockTrpcCloudTask.retry.mutate.mockReturnValueOnce(
      new Promise<void>(() => {}),
    );
    sessionStoreSetters.updateSession(RUN_ID, { status: "disconnected" });

    const sendResult = await service.sendPrompt(TASK_ID, "lol");
    expect(sendResult.stopReason).toBe("queued");

    const afterQueue = useSessionStore.getState().sessions[RUN_ID];
    expect(afterQueue?.status).toBe("disconnected");
    expect(afterQueue?.messageQueue).toHaveLength(1);
    expect(afterQueue?.messageQueue[0]?.content).toBe("lol");
    // Pre-fix: nothing below would ever drain this. It would stay "Queued"
    // forever (no fresh run_started/turn_complete arrives for an idle run).
    expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();

    // --- Phase C: watcher reconnects, refetches run state = in_progress ----
    // The status-driven recovery path must observe the agent already booted
    // for THIS run, flip disconnected -> connected, and drain the queue.
    onData({
      kind: "status",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
    });

    await vi.waitFor(() => {
      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
        expect.objectContaining({
          taskId: TASK_ID,
          runId: RUN_ID,
          method: "user_message",
          params: expect.objectContaining({ content: "lol" }),
        }),
      );
    });

    const recovered = useSessionStore.getState().sessions[RUN_ID];
    expect(recovered?.status).toBe("connected");
    expect(recovered?.messageQueue).toHaveLength(0);
  });

  it("drains a queue stranded on an idle disconnected run via the real retry path (no injected status update)", async () => {
    const service = getSessionService();
    service.watchCloudTask(
      TASK_ID,
      RUN_ID,
      "https://api.anthropic.com",
      123,
      undefined,
      "https://logs.example.com/run",
    );

    // An idle, already-bootstrapped run that completed its turn for THIS run
    // (live idle flag set) then dropped to disconnected on an SSE blip. The
    // api.py-side run is still alive, so cloudStatus stays in_progress.
    sessionStoreSetters.setSession(
      makeBaseSession({
        status: "disconnected",
        cloudStatus: "in_progress",
        agentIdleForRunId: RUN_ID,
      }),
    );

    // User sends a message while disconnected. sendCloudPrompt's queue gate
    // enqueues it and fires retryCloudTaskWatch() (status is disconnected).
    // The main-process retry of an already-bootstrapped watcher only
    // reconnects SSE with start=latest and, for an idle run, delivers NO
    // fresh status/snapshot — so NOTHING is injected via onData here. This
    // is the exact production shape of the original deadlock.
    const sendResult = await service.sendPrompt(TASK_ID, "lol");
    expect(sendResult.stopReason).toBe("queued");
    expect(
      useSessionStore.getState().sessions[RUN_ID]?.messageQueue,
    ).toHaveLength(1);

    // No onData(...) is ever called. The queue must still drain, purely from
    // the post-retry recovery inside retryCloudTaskWatch().
    await vi.waitFor(() => {
      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
        expect.objectContaining({
          taskId: TASK_ID,
          runId: RUN_ID,
          method: "user_message",
          params: expect.objectContaining({ content: "lol" }),
        }),
      );
    });
    const drained = useSessionStore.getState().sessions[RUN_ID];
    expect(drained?.status).toBe("connected");
    expect(drained?.messageQueue).toHaveLength(0);
  });

  it.each<AgentSession["status"]>(["disconnected", "error"])(
    "drains a stranded queue when the server reports the sandbox stopped and the session is %s",
    async (status) => {
      const service = getSessionService();
      service.watchCloudTask(
        TASK_ID,
        RUN_ID,
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run",
      );
      const onData = latestOnData();

      const rawPrompt: ContentBlock = { type: "text", text: "lol" };
      sessionStoreSetters.setSession(
        makeBaseSession({
          status,
          messageQueue: [
            { id: "q-1", content: "lol", rawPrompt: [rawPrompt], queuedAt: 1 },
          ],
        }),
      );

      onData({
        kind: "status",
        taskId: TASK_ID,
        runId: RUN_ID,
        status: "in_progress",
        sandboxAlive: false,
      });

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
          expect.objectContaining({
            taskId: TASK_ID,
            runId: RUN_ID,
            method: "user_message",
            params: expect.objectContaining({ content: "lol" }),
          }),
        );
      });
      const drained = useSessionStore.getState().sessions[RUN_ID];
      expect(drained?.messageQueue).toHaveLength(0);
    },
  );

  it("does not drain while the agent is still booting (boot race protected)", async () => {
    const service = getSessionService();
    service.watchCloudTask(
      TASK_ID,
      RUN_ID,
      "https://api.anthropic.com",
      123,
      undefined,
      "https://logs.example.com/run",
    );
    const onData = latestOnData();

    // Disconnected, queued message, but the agent has NEVER booted for this
    // run (no run_started/turn_complete, no agentIdleForRunId). Draining now
    // would race sendInitialTaskMessage/sendResumeMessage.
    const queued: ContentBlock = { type: "text", text: "lol" };
    sessionStoreSetters.setSession(
      makeBaseSession({
        status: "disconnected",
        messageQueue: [
          { id: "q-1", content: "lol", rawPrompt: [queued], queuedAt: 1 },
        ],
      }),
    );

    onData({
      kind: "status",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
    });

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
    expect(useSessionStore.getState().sessions[RUN_ID]?.status).toBe(
      "disconnected",
    );
    expect(
      useSessionStore.getState().sessions[RUN_ID]?.messageQueue,
    ).toHaveLength(1);
  });

  it("does not drain on a current-run run_started snapshot until turn_complete (initial/resume turn race)", async () => {
    const service = getSessionService();
    service.watchCloudTask(
      TASK_ID,
      RUN_ID,
      "https://api.anthropic.com",
      123,
      undefined,
      "https://logs.example.com/run",
    );
    const onData = latestOnData();

    // Disconnected, queued message. The agent has NOT completed a turn for
    // this run (no agentIdleForRunId, no turn_complete).
    const queued: ContentBlock = { type: "text", text: "lol" };
    sessionStoreSetters.setSession(
      makeBaseSession({
        status: "disconnected",
        messageQueue: [
          { id: "q-1", content: "lol", rawPrompt: [queued], queuedAt: 1 },
        ],
      }),
    );

    // A snapshot delivers THIS run's _posthog/run_started AND status
    // in_progress. The run_started handler flips status -> "connected", and
    // the same in_progress snapshot then calls the recovery helper. Status
    // is now "connected" but the agent is mid-boot: the initial/resume turn
    // starts right after run_started. Draining here races
    // sendInitialTaskMessage/sendResumeMessage — it must NOT drain.
    const runStartedEvent = {
      type: "acp_message" as const,
      ts: 1,
      message: {
        jsonrpc: "2.0" as const,
        method: "_posthog/run_started",
        params: {
          sessionId: "acp-session",
          runId: RUN_ID,
          taskId: TASK_ID,
          agentVersion: "1.2.3",
        },
      },
    };
    mockConvertStoredEntriesToEvents.mockReturnValueOnce([runStartedEvent]);
    onData({
      kind: "snapshot",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
      newEntries: [{ notification: { method: "_posthog/run_started" } }],
      totalEntryCount: 1,
    });

    await new Promise((resolve) => setTimeout(resolve, 0));
    // run_started brought the session to "connected", but the queue must
    // stay put: run_started alone is not idle.
    expect(useSessionStore.getState().sessions[RUN_ID]?.status).toBe(
      "connected",
    );
    expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
    expect(
      useSessionStore.getState().sessions[RUN_ID]?.messageQueue,
    ).toHaveLength(1);

    // The initial/resume turn finally completes -> NOW it is safe to drain.
    const turnCompleteEvent = {
      type: "acp_message" as const,
      ts: 2,
      message: {
        jsonrpc: "2.0" as const,
        method: "_posthog/turn_complete",
        params: { sessionId: "acp-session", stopReason: "end_turn" },
      },
    };
    const processedBeforeTurnComplete =
      useSessionStore.getState().sessions[RUN_ID]?.processedLineCount ?? 0;
    mockConvertStoredEntriesToEvents.mockReturnValueOnce([turnCompleteEvent]);
    onData({
      kind: "snapshot",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
      newEntries: [{ notification: { method: "_posthog/turn_complete" } }],
      totalEntryCount: processedBeforeTurnComplete + 1,
    });

    await vi.waitFor(() => {
      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
        expect.objectContaining({
          taskId: TASK_ID,
          runId: RUN_ID,
          method: "user_message",
          params: expect.objectContaining({ content: "lol" }),
        }),
      );
    });
    const drained = useSessionStore.getState().sessions[RUN_ID];
    expect(drained?.status).toBe("connected");
    expect(drained?.messageQueue).toHaveLength(0);
  });

  it("does not dispatch a queued follow-up mid-turn after retryCloudTaskWatch clears isPromptPending", async () => {
    const service = getSessionService();
    service.watchCloudTask(
      TASK_ID,
      RUN_ID,
      "https://api.anthropic.com",
      123,
      undefined,
      "https://logs.example.com/run",
    );
    const onData = latestOnData();

    // Agent booted and idle from a prior turn.
    sessionStoreSetters.setSession(
      makeBaseSession({ status: "connected", agentIdleForRunId: RUN_ID }),
    );

    // A new turn starts: the agent receives a session/prompt. The real
    // handler must clear the idle marker (a turn is now in flight) — even
    // though no turn_complete has arrived yet.
    const promptEvent = {
      type: "acp_message" as const,
      ts: Date.now(),
      message: {
        jsonrpc: "2.0" as const,
        id: 1,
        method: "session/prompt",
        params: { prompt: [{ type: "text", text: "do the work" }] },
      },
    };
    mockConvertStoredEntriesToEvents.mockReturnValueOnce([promptEvent]);
    onData({
      kind: "snapshot",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
      newEntries: [{ notification: { method: "session/prompt" } }],
      totalEntryCount: 1,
    });

    await vi.waitFor(() => {
      const s = useSessionStore.getState().sessions[RUN_ID];
      expect(s?.isPromptPending).toBe(true);
      expect(s?.agentIdleForRunId).not.toBe(RUN_ID);
    });

    // SSE drops; retryCloudTaskWatch forcibly clears isPromptPending even
    // though the remote turn is still running. The idle marker stays
    // cleared — that is the signal recovery must trust, not isPromptPending.
    await service.retryCloudTaskWatch(TASK_ID);
    const afterRetry = useSessionStore.getState().sessions[RUN_ID];
    expect(afterRetry?.status).toBe("disconnected");
    expect(afterRetry?.isPromptPending).toBe(false);
    expect(afterRetry?.agentIdleForRunId).not.toBe(RUN_ID);

    // User sends a follow-up while disconnected -> it queues.
    const onDataAfterRetry = latestOnData();
    const sendResult = await service.sendPrompt(TASK_ID, "follow up");
    expect(sendResult.stopReason).toBe("queued");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(
      useSessionStore.getState().sessions[RUN_ID]?.messageQueue,
    ).toHaveLength(1);

    // Watcher reconnects, refetches run state = in_progress. Recovery must
    // NOT fire: the agent is mid-turn (idle marker cleared, turn_complete
    // not yet seen). Dispatching now is the race this guards against.
    onDataAfterRetry({
      kind: "status",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
    expect(useSessionStore.getState().sessions[RUN_ID]?.status).toBe(
      "disconnected",
    );
    expect(
      useSessionStore.getState().sessions[RUN_ID]?.messageQueue,
    ).toHaveLength(1);

    // The in-flight turn finally completes -> NOW it is safe to drain.
    const turnCompleteEvent = {
      type: "acp_message" as const,
      ts: Date.now(),
      message: {
        jsonrpc: "2.0" as const,
        method: "_posthog/turn_complete",
        params: { sessionId: "acp-session", stopReason: "end_turn" },
      },
    };
    mockConvertStoredEntriesToEvents.mockReturnValueOnce([turnCompleteEvent]);
    onDataAfterRetry({
      kind: "snapshot",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
      newEntries: [
        { notification: { method: "session/prompt" } },
        { notification: { method: "_posthog/turn_complete" } },
      ],
      totalEntryCount: 2,
    });

    await vi.waitFor(() => {
      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
        expect.objectContaining({
          taskId: TASK_ID,
          method: "user_message",
          params: expect.objectContaining({ content: "follow up" }),
        }),
      );
    });
    const drained = useSessionStore.getState().sessions[RUN_ID];
    expect(drained?.status).toBe("connected");
    expect(drained?.messageQueue).toHaveLength(0);
  });

  it("clears the idle marker when sendCloudPrompt starts a turn even if the session/prompt log never arrives", async () => {
    const service = getSessionService();
    service.watchCloudTask(
      TASK_ID,
      RUN_ID,
      "https://api.anthropic.com",
      123,
      undefined,
      "https://logs.example.com/run",
    );

    // Agent booted and idle from a prior turn.
    sessionStoreSetters.setSession(
      makeBaseSession({ status: "connected", agentIdleForRunId: RUN_ID }),
    );

    // User sends a prompt while connected -> sendCloudPrompt starts a turn.
    // The cloud accepts it into the running sandbox. Crucially NO polled
    // session/prompt echo is ever delivered (the SSE drops first), so the
    // only thing that can clear the now-stale idle marker is the
    // sendCloudPrompt turn-start update itself.
    mockTrpcCloudTask.sendCommand.mutate.mockResolvedValueOnce({
      success: true,
      result: { queued: true },
    });
    await service.sendPrompt(TASK_ID, "do the work");

    const afterSend = useSessionStore.getState().sessions[RUN_ID];
    expect(afterSend?.isPromptPending).toBe(true);
    expect(afterSend?.agentIdleForRunId).not.toBe(RUN_ID);
    expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledTimes(1);

    // SSE drops; retryCloudTaskWatch forcibly clears isPromptPending even
    // though the remote turn is still running. The idle marker stays
    // cleared — that is the signal recovery must trust, not isPromptPending.
    await service.retryCloudTaskWatch(TASK_ID);
    const afterRetry = useSessionStore.getState().sessions[RUN_ID];
    expect(afterRetry?.status).toBe("disconnected");
    expect(afterRetry?.isPromptPending).toBe(false);
    expect(afterRetry?.agentIdleForRunId).not.toBe(RUN_ID);

    // User queues a follow-up while disconnected.
    const onDataAfterRetry = latestOnData();
    const sendResult = await service.sendPrompt(TASK_ID, "follow up");
    expect(sendResult.stopReason).toBe("queued");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(
      useSessionStore.getState().sessions[RUN_ID]?.messageQueue,
    ).toHaveLength(1);

    // Reconnect -> in_progress. Recovery must NOT fire mid-turn: the idle
    // marker is cleared and no turn_complete has arrived for the in-flight
    // turn. Without the sendCloudPrompt clear, a stale idle marker would
    // make this drain the follow-up while the first turn is still running.
    onDataAfterRetry({
      kind: "status",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledTimes(1);
    expect(useSessionStore.getState().sessions[RUN_ID]?.status).toBe(
      "disconnected",
    );
    expect(
      useSessionStore.getState().sessions[RUN_ID]?.messageQueue,
    ).toHaveLength(1);

    // The in-flight turn finally completes -> NOW it is safe to drain.
    // Anchor totalEntryCount to the live processedLineCount so the delta is
    // deterministically positive regardless of what the reconnect hydrate
    // set it to (a fixed count can hit the no-delta dedup guard).
    const turnCompleteEvent = {
      type: "acp_message" as const,
      ts: Date.now(),
      message: {
        jsonrpc: "2.0" as const,
        method: "_posthog/turn_complete",
        params: { sessionId: "acp-session", stopReason: "end_turn" },
      },
    };
    const processedBeforeTurnComplete =
      useSessionStore.getState().sessions[RUN_ID]?.processedLineCount ?? 0;
    mockConvertStoredEntriesToEvents.mockReturnValueOnce([turnCompleteEvent]);
    onDataAfterRetry({
      kind: "snapshot",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
      newEntries: [{ notification: { method: "_posthog/turn_complete" } }],
      totalEntryCount: processedBeforeTurnComplete + 1,
    });

    await vi.waitFor(() => {
      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
        expect.objectContaining({
          taskId: TASK_ID,
          method: "user_message",
          params: expect.objectContaining({ content: "follow up" }),
        }),
      );
    });
    const drained = useSessionStore.getState().sessions[RUN_ID];
    expect(drained?.status).toBe("connected");
    expect(drained?.messageQueue).toHaveLength(0);
  });

  it("does not recover from a prior run's turn_complete carried into the resumed session", async () => {
    const service = getSessionService();
    service.watchCloudTask(
      TASK_ID,
      RUN_ID,
      "https://api.anthropic.com",
      123,
      undefined,
      "https://logs.example.com/run",
    );
    const onData = latestOnData();

    // resumeCloudRun copies the PREVIOUS run's history into the new run's
    // session. The prior run's run_started + turn_complete must NOT make the
    // new run look idle before its own resume turn completes. No live flag
    // (recreated from logs); no current-run run_started in events yet.
    const priorRunStarted = {
      type: "acp_message" as const,
      ts: 1,
      message: {
        jsonrpc: "2.0" as const,
        method: "_posthog/run_started",
        params: { sessionId: "old", runId: "old-run", taskId: TASK_ID },
      },
    };
    const priorTurnComplete = {
      type: "acp_message" as const,
      ts: 2,
      message: {
        jsonrpc: "2.0" as const,
        method: "_posthog/turn_complete",
        params: { sessionId: "old", stopReason: "end_turn" },
      },
    };
    sessionStoreSetters.setSession(
      makeBaseSession({
        status: "disconnected",
        events: [priorRunStarted, priorTurnComplete],
        messageQueue: [{ id: "q-1", content: "follow up", queuedAt: 1 }],
      }),
    );

    onData({
      kind: "status",
      taskId: TASK_ID,
      runId: RUN_ID,
      status: "in_progress",
    });

    await new Promise((resolve) => setTimeout(resolve, 0));
    // With the real store, a missing current-run boundary would let the
    // prior turn_complete recover -> connected -> drain. Assert it stays put.
    expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
    expect(useSessionStore.getState().sessions[RUN_ID]?.status).toBe(
      "disconnected",
    );
    expect(
      useSessionStore.getState().sessions[RUN_ID]?.messageQueue,
    ).toHaveLength(1);
  });
});

import type {
  ContentBlock,
  SessionConfigOption,
  SessionConfigSelectGroup,
} from "@agentclientprotocol/sdk";
import type { AcpMessage } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import type { AgentSession } from "@posthog/ui/features/sessions/sessionStore";
import { beforeEach, describe, expect, it, vi } from "vitest";

// --- Hoisted Mocks ---

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

const mockTrpcSkills = vi.hoisted(() => ({
  list: { query: vi.fn() },
  bundleLocal: { query: vi.fn() },
  resolveDependencies: { query: vi.fn() },
}));

const mockTrpcHandoff = vi.hoisted(() => ({
  preflightToCloud: { query: vi.fn() },
  executeToCloud: { mutate: vi.fn() },
}));

const mockTrpcOs = vi.hoisted(() => ({
  openExternal: { mutate: vi.fn() },
}));

const mockSessionStoreSetters = vi.hoisted(() => ({
  setSession: vi.fn(),
  removeSession: vi.fn(),
  updateSession: vi.fn(),
  updateCloudStatus: vi.fn(),
  appendEvents: vi.fn(),
  enqueueMessage: vi.fn(),
  removeQueuedMessage: vi.fn(),
  updateQueuedMessage: vi.fn(),
  setEditingQueuedMessage: vi.fn(),
  clearEditingQueuedMessage: vi.fn(),
  clearMessageQueue: vi.fn(),
  dequeueMessagesAsText: vi.fn((): string | null => null),
  dequeueMessages: vi.fn(
    () =>
      [] as Array<{
        id: string;
        content: string;
        rawPrompt?: unknown;
        queuedAt: number;
      }>,
  ),
  prependQueuedMessages: vi.fn(),
  setPendingPermissions: vi.fn(),
  getSessionByTaskId: vi.fn(),
  getSessions: vi.fn(() => ({})),
  clearAll: vi.fn(),
  appendOptimisticItem: vi.fn(),
  clearOptimisticItems: vi.fn(),
  clearTailOptimisticItems: vi.fn(),
  replaceOptimisticWithEvent: vi.fn(),
}));

const mockGetConfigOptionByCategory = vi.hoisted(() =>
  vi.fn(
    (
      _configOptions?: Array<{ category?: string }>,
      _category?: string,
    ): { category?: string } | undefined => undefined,
  ),
);

vi.mock("@posthog/ui/features/sessions/sessionStore", () => ({
  sessionStoreSetters: mockSessionStoreSetters,
  getConfigOptionByCategory: mockGetConfigOptionByCategory,
  mergeConfigOptions: vi.fn((live: unknown[], _persisted: unknown[]) => live),
  flattenSelectOptions: vi.fn(
    (options: Array<{ options?: unknown[] }> | undefined) => {
      if (!options?.length) return [];
      const first = options[0] as { options?: unknown[] };
      if (first && Array.isArray(first.options)) {
        return options.flatMap(
          (group) => (group as { options: unknown[] }).options,
        );
      }
      return options;
    },
  ),
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
  presignTaskRunArtifact: vi.fn(),
  startGithubUserIntegrationConnect: vi.fn(),
  getTaskRunSessionLogs: vi.fn(),
  getTaskRunSessionLogsResult: vi.fn(),
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
  getPersistedConfigOptions: vi.fn<
    (taskRunId: string) => SessionConfigOption[] | undefined
  >(() => undefined),
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

const mockSpeechNotifier = vi.hoisted(() => ({
  speak: vi.fn(),
}));

const mockFeatureFlags = vi.hoisted(() => ({
  isEnabled: vi.fn(() => false),
  onFlagsLoaded: vi.fn(() => vi.fn()),
}));

const mockSettingsState = vi.hoisted(() => ({
  customInstructions: "",
  spokenNotifications: false,
  syncCustomInstructionsFromFile: false,
  syncedCustomInstructions: null as {
    path: string;
    displayPath: string;
    content: string;
    truncated: boolean;
  } | null,
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
vi.mock("@posthog/di/container", () => ({
  resolveService: (token: unknown) => {
    if (token === Symbol.for("posthog.host.trpcClient")) {
      return {
        agent: mockTrpcAgent,
        workspace: mockTrpcWorkspace,
        logs: mockTrpcLogs,
        cloudTask: mockTrpcCloudTask,
        fs: mockTrpcFs,
        skills: mockTrpcSkills,
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
    if (typeof token === "function" && token.name === "SpeechNotifier") {
      return mockSpeechNotifier;
    }
    if (token === Symbol.for("posthog.ui.featureFlags")) {
      return mockFeatureFlags;
    }
    throw new Error(`resolveService: unmocked token ${String(token)}`);
  },
}));
vi.mock("@posthog/shared", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@posthog/shared")>()),
  getCloudUrlFromRegion: () => "https://api.anthropic.com",
  getConfigOptionByCategory: mockGetConfigOptionByCategory,
  mergeConfigOptions: (await importOriginal<typeof import("@posthog/shared")>())
    .mergeConfigOptions,
  flattenSelectOptions: vi.fn(
    (options: Array<{ options?: unknown[] }> | undefined) => {
      if (!options?.length) return [];
      const first = options[0] as { options?: unknown[] };
      if (first && Array.isArray(first.options)) {
        return options.flatMap(
          (group) => (group as { options: unknown[] }).options,
        );
      }
      return options;
    },
  ),
}));
const mockConvertStoredEntriesToEvents = vi.hoisted(() =>
  vi.fn<
    (
      entries: unknown[],
      taskDescription?: string,
      positionOptions?: unknown,
    ) => unknown[]
  >(() => []),
);

vi.mock("@posthog/core/sessions/sessionEvents", async () => {
  const actual = await vi.importActual<
    typeof import("@posthog/core/sessions/sessionEvents")
  >("@posthog/core/sessions/sessionEvents");
  return {
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
    getStoredLogEventPosition: actual.getStoredLogEventPosition,
    getUserShellExecutesSinceLastPrompt: vi.fn(() => []),
    hasSessionPromptEvent: actual.hasSessionPromptEvent,
    isAbsoluteFolderPath: actual.isAbsoluteFolderPath,
    isFatalSessionError: actual.isFatalSessionError,
    isRateLimitError: actual.isRateLimitError,
    isTurnCompleteEvent: actual.isTurnCompleteEvent,
    normalizePromptToBlocks: vi.fn((p) =>
      typeof p === "string" ? [{ type: "text", text: p }] : p,
    ),
    promptReferencesAbsoluteFolder: actual.promptReferencesAbsoluteFolder,
    shellExecutesToContextBlocks: vi.fn(() => []),
  };
});

import { toast } from "@posthog/ui/primitives/toast";
import {
  getSessionService,
  resetSessionService,
  shouldEnableSpokenNarration,
} from "./sessionServiceHost";

// --- Test Fixtures ---

const createMockTask = (overrides: Partial<Task> = {}): Task => ({
  id: "task-123",
  task_number: 1,
  slug: "test-task",
  title: "Test Task",
  description: "Test description",
  origin_product: "twig",
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  ...overrides,
});

const createMockSession = (
  overrides: Partial<AgentSession> = {},
): AgentSession => ({
  taskRunId: "run-123",
  taskId: "task-123",
  taskTitle: "Test Task",
  channel: "agent-event:run-123",
  events: [],
  startedAt: Date.now(),
  status: "connected",
  isPromptPending: false,
  isCompacting: false,
  promptStartedAt: null,
  pendingPermissions: new Map(),
  pausedDurationMs: 0,
  messageQueue: [],
  optimisticItems: [],
  ...overrides,
});

// --- Tests ---

describe("SessionService", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockConvertStoredEntriesToEvents.mockImplementation(() => []);
    resetSessionService();
    mockSettingsState.customInstructions = "";
    mockSettingsState.spokenNotifications = false;
    mockFeatureFlags.isEnabled.mockReturnValue(false);
    mockSettingsState.syncCustomInstructionsFromFile = false;
    mockSettingsState.syncedCustomInstructions = null;
    mockGetIsOnline.mockReturnValue(true);
    mockGetConfigOptionByCategory.mockReturnValue(undefined);
    mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
    mockAuthenticatedClient.getTaskRunSessionLogs.mockResolvedValue([]);
    mockSessionConfigStore.getPersistedConfigOptions.mockReturnValue(undefined);
    mockAdapterFns.getAdapter.mockReturnValue(undefined);
    mockAuthenticatedClient.getTaskRunSessionLogsResult.mockResolvedValue({
      entries: [],
      complete: true,
    });
    mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);
    mockSessionStoreSetters.getSessions.mockReturnValue({});
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
    mockTrpcFs.readFileAsBase64.query.mockResolvedValue(null);
    mockTrpcSkills.list.query.mockResolvedValue([]);
    mockTrpcSkills.bundleLocal.query.mockRejectedValue(
      new Error("Unexpected skill bundle upload"),
    );
    // Dependency resolution is a no-op passthrough by default (no declared deps).
    mockTrpcSkills.resolveDependencies.query.mockImplementation(
      async (refs: unknown) => refs,
    );
    mockTrpcHandoff.preflightToCloud.query.mockResolvedValue({
      canHandoff: true,
    });
    mockTrpcHandoff.executeToCloud.mutate.mockResolvedValue({
      success: true,
      logEntryCount: 0,
    });
    mockTrpcOs.openExternal.mutate.mockResolvedValue(undefined);
    mockAuthenticatedClient.prepareTaskRunArtifactUploads.mockResolvedValue([]);
    mockAuthenticatedClient.finalizeTaskRunArtifactUploads.mockResolvedValue(
      [],
    );
    mockAuthenticatedClient.prepareTaskStagedArtifactUploads.mockResolvedValue(
      [],
    );
    mockAuthenticatedClient.finalizeTaskStagedArtifactUploads.mockResolvedValue(
      [],
    );
    mockAuthenticatedClient.startGithubUserIntegrationConnect.mockResolvedValue(
      {
        install_url: "https://github.com/login/oauth/authorize",
        connect_flow: "oauth_authorize",
      },
    );
  });

  describe("singleton management", () => {
    it("returns the same instance on multiple calls", () => {
      const instance1 = getSessionService();
      const instance2 = getSessionService();
      expect(instance1).toBe(instance2);
    });

    it("creates new instance after reset", () => {
      const instance1 = getSessionService();
      resetSessionService();
      const instance2 = getSessionService();
      expect(instance1).not.toBe(instance2);
    });

    it("handles reset when no instance exists", () => {
      expect(() => resetSessionService()).not.toThrow();
    });
  });

  describe("spoken narration availability", () => {
    it.each([
      {
        userOptedIn: true,
        flagEnabled: true,
        isDevelopment: false,
        expected: true,
      },
      {
        userOptedIn: false,
        flagEnabled: true,
        isDevelopment: false,
        expected: false,
      },
      {
        userOptedIn: true,
        flagEnabled: false,
        isDevelopment: false,
        expected: false,
      },
      {
        userOptedIn: true,
        flagEnabled: false,
        isDevelopment: true,
        expected: true,
      },
    ])(
      "returns $expected for opt-in=$userOptedIn flag=$flagEnabled dev=$isDevelopment",
      ({ userOptedIn, flagEnabled, isDevelopment, expected }) => {
        expect(
          shouldEnableSpokenNarration(userOptedIn, flagEnabled, isDevelopment),
        ).toBe(expected);
      },
    );
  });

  describe("cloud attachment previews", () => {
    it("deduplicates concurrent manifest requests for the same run", async () => {
      mockAuthenticatedClient.getTaskRun.mockResolvedValue({
        artifacts: [
          {
            id: "artifact-1",
            storage_path: "tasks/run-123/artifacts/one.png",
          },
          {
            id: "artifact-2",
            storage_path: "tasks/run-123/artifacts/two.png",
          },
        ],
      });
      mockAuthenticatedClient.presignTaskRunArtifact.mockImplementation(
        async (_taskId, _runId, storagePath) =>
          `https://s3.example.com/${storagePath}`,
      );
      const service = getSessionService();

      await Promise.all([
        service.getCloudAttachmentPreviewUrl(
          "task-123",
          "run-123",
          "artifact-1",
        ),
        service.getCloudAttachmentPreviewUrl(
          "task-123",
          "run-123",
          "artifact-2",
        ),
      ]);

      expect(mockAuthenticatedClient.getTaskRun).toHaveBeenCalledTimes(1);
      expect(
        mockAuthenticatedClient.presignTaskRunArtifact,
      ).toHaveBeenCalledTimes(2);
    });

    it("does not share manifest requests across projects", async () => {
      const resolvers: Array<(value: { artifacts: unknown[] }) => void> = [];
      mockAuthenticatedClient.getTaskRun.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolvers.push(resolve);
          }),
      );
      const service = getSessionService();
      const first = service.getCloudAttachmentPreviewUrl(
        "task-123",
        "run-123",
        "artifact-1",
      );
      await vi.waitFor(() =>
        expect(mockAuthenticatedClient.getTaskRun).toHaveBeenCalledTimes(1),
      );

      mockAuth.fetchAuthState.mockResolvedValue({
        status: "authenticated",
        bootstrapComplete: true,
        cloudRegion: "us",
        orgProjectsMap: {},
        currentOrgId: "org-2",
        currentProjectId: 456,
        hasCodeAccess: true,
        needsScopeReauth: false,
      });
      const second = service.getCloudAttachmentPreviewUrl(
        "task-123",
        "run-123",
        "artifact-1",
      );
      await vi.waitFor(() =>
        expect(mockAuthenticatedClient.getTaskRun).toHaveBeenCalledTimes(2),
      );

      for (const resolve of resolvers) resolve({ artifacts: [] });
      await Promise.all([first, second]);
    });

    it("resolves an artifact id to a presigned URL", async () => {
      mockAuthenticatedClient.getTaskRun.mockResolvedValue({
        artifacts: [
          {
            id: "artifact-456",
            storage_path: "tasks/run-123/artifacts/screenshot.png",
          },
        ],
      });
      mockAuthenticatedClient.presignTaskRunArtifact.mockResolvedValue(
        "https://s3.example.com/screenshot.png?signature=abc",
      );

      await expect(
        getSessionService().getCloudAttachmentPreviewUrl(
          "task-123",
          "run-123",
          "artifact-456",
        ),
      ).resolves.toBe("https://s3.example.com/screenshot.png?signature=abc");
      expect(
        mockAuthenticatedClient.presignTaskRunArtifact,
      ).toHaveBeenCalledWith(
        "task-123",
        "run-123",
        "tasks/run-123/artifacts/screenshot.png",
      );
    });

    it("returns null when the artifact is absent", async () => {
      mockAuthenticatedClient.getTaskRun.mockResolvedValue({ artifacts: [] });

      await expect(
        getSessionService().getCloudAttachmentPreviewUrl(
          "task-123",
          "run-123",
          "missing",
        ),
      ).resolves.toBeNull();
      expect(
        mockAuthenticatedClient.presignTaskRunArtifact,
      ).not.toHaveBeenCalled();
    });

    it("returns null when authentication is unavailable", async () => {
      mockAuth.fetchAuthState.mockResolvedValue({
        status: "anonymous",
        bootstrapComplete: true,
      });

      await expect(
        getSessionService().getCloudAttachmentPreviewUrl(
          "task-123",
          "run-123",
          "artifact-456",
        ),
      ).resolves.toBeNull();
      expect(mockAuthenticatedClient.getTaskRun).not.toHaveBeenCalled();
    });

    it("returns null when presigning fails", async () => {
      mockAuthenticatedClient.getTaskRun.mockResolvedValue({
        artifacts: [
          {
            id: "artifact-456",
            storage_path: "tasks/run-123/artifacts/screenshot.png",
          },
        ],
      });
      mockAuthenticatedClient.presignTaskRunArtifact.mockRejectedValue(
        new Error("presign unavailable"),
      );

      await expect(
        getSessionService().getCloudAttachmentPreviewUrl(
          "task-123",
          "run-123",
          "artifact-456",
        ),
      ).resolves.toBeNull();
    });
  });

  describe("connectToTask", () => {
    it("skips local connection for cloud runs", async () => {
      const service = getSessionService();

      await service.connectToTask({
        task: createMockTask({
          latest_run: {
            id: "run-123",
            task: "task-123",
            team: 123,
            environment: "cloud",
            status: "in_progress",
            log_url: "https://logs.example.com/run-123",
            error_message: null,
            output: null,
            state: {},
            branch: "main",
            created_at: "2024-01-01T00:00:00Z",
            updated_at: "2024-01-01T00:00:00Z",
            completed_at: null,
          },
        }),
        repoPath: "/repo",
      });

      expect(mockAuth.fetchAuthState).not.toHaveBeenCalled();
      expect(mockTrpcAgent.reconnect.mutate).not.toHaveBeenCalled();
      expect(mockSessionStoreSetters.setSession).not.toHaveBeenCalled();
    });

    it("skips connection if already connected", async () => {
      const service = getSessionService();
      const mockSession = createMockSession({ status: "connected" });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);

      await service.connectToTask({
        task: createMockTask(),
        repoPath: "/repo",
      });

      expect(mockTrpcAgent.start.mutate).not.toHaveBeenCalled();
    });

    it("skips connection if already connecting", async () => {
      const service = getSessionService();
      const mockSession = createMockSession({ status: "connecting" });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);

      await service.connectToTask({
        task: createMockTask(),
        repoPath: "/repo",
      });

      expect(mockTrpcAgent.start.mutate).not.toHaveBeenCalled();
    });

    it("starts the session with the synced file content when file sync is on", async () => {
      // Pins the host wiring at sessionServiceHost.ts: the settings getter runs
      // the store through getEffectiveCustomInstructions, so the synced file -
      // not the hand-typed instructions - reaches agent.start. Reverting that
      // to a plain state.customInstructions pass-through would send "typed".
      const service = getSessionService();
      mockSettingsState.customInstructions = "typed";
      mockSettingsState.syncCustomInstructionsFromFile = true;
      mockSettingsState.syncedCustomInstructions = {
        path: "/home/u/.claude/CLAUDE.md",
        displayPath: "~/.claude/CLAUDE.md",
        content: "synced from file",
        truncated: false,
      };

      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);
      mockBuildAuthenticatedClient.mockReturnValue({
        ...mockAuthenticatedClient,
        createTaskRun: vi.fn().mockResolvedValue({ id: "run-789" }),
        appendTaskRunLog: vi.fn(),
      });
      mockTrpcAgent.start.mutate.mockResolvedValue({
        channel: "test-channel",
        configOptions: [],
      });

      await service.connectToTask({
        task: createMockTask(),
        repoPath: "/repo",
      });

      expect(mockTrpcAgent.start.mutate).toHaveBeenCalledWith(
        expect.objectContaining({ customInstructions: "synced from file" }),
      );
    });

    it("deduplicates concurrent connection attempts", async () => {
      const service = getSessionService();

      // Setup: no existing session initially
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);

      // Track how many times createTaskRun is called
      const createTaskRunMock = vi.fn().mockResolvedValue({ id: "run-123" });
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
      mockBuildAuthenticatedClient.mockReturnValue({
        ...mockAuthenticatedClient,
        createTaskRun: createTaskRunMock,
        appendTaskRunLog: vi.fn(),
      });

      mockTrpcAgent.start.mutate.mockResolvedValue({
        channel: "test-channel",
        currentModelId: "claude-3-opus",
        availableModels: [],
      });
      mockTrpcAgent.onSessionEvent.subscribe.mockReturnValue({
        unsubscribe: vi.fn(),
      });
      mockTrpcAgent.onPermissionRequest.subscribe.mockReturnValue({
        unsubscribe: vi.fn(),
      });

      const task = createMockTask();

      // Make two concurrent connection attempts
      await Promise.all([
        service.connectToTask({ task, repoPath: "/repo" }),
        service.connectToTask({ task, repoPath: "/repo" }),
      ]);

      // createTaskRun should only be called once due to deduplication
      expect(createTaskRunMock).toHaveBeenCalledTimes(1);
    });

    it("creates error session when offline", async () => {
      mockGetIsOnline.mockReturnValue(false);
      const service = getSessionService();

      await service.connectToTask({
        task: createMockTask(),
        repoPath: "/repo",
      });

      expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
        expect.objectContaining({
          status: "disconnected",
          errorMessage: expect.stringContaining("No internet connection"),
        }),
      );
    });

    it("creates error session when auth is missing", async () => {
      const service = getSessionService();

      mockAuth.fetchAuthState.mockResolvedValue({
        status: "anonymous",
        bootstrapComplete: true,
        cloudRegion: null,
        orgProjectsMap: {},
        currentOrgId: null,
        currentProjectId: null,
        hasCodeAccess: null,
        needsScopeReauth: false,
      });
      mockBuildAuthenticatedClient.mockReturnValue(null);

      await service.connectToTask({
        task: createMockTask(),
        repoPath: "/repo",
      });

      expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
        expect.objectContaining({
          status: "error",
          errorMessage: expect.stringContaining("Authentication required"),
        }),
      );
    });

    it("keeps the session connecting while auth restores, then recovers", async () => {
      vi.useFakeTimers();
      try {
        const service = getSessionService();
        const clearSpy = vi
          .spyOn(service, "clearSessionError")
          .mockResolvedValue(undefined);
        const initialPrompt: ContentBlock[] = [
          { type: "text", text: "do the thing" },
        ];

        mockAuth.fetchAuthState.mockResolvedValue({
          status: "restoring",
          bootstrapComplete: false,
          cloudRegion: "us",
          orgProjectsMap: {},
          currentOrgId: null,
          currentProjectId: 123,
          hasCodeAccess: null,
          needsScopeReauth: false,
        });

        const promise = service.connectToTask({
          task: createMockTask(),
          repoPath: "/repo",
          initialPrompt,
        });
        await vi.advanceTimersByTimeAsync(0);

        expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
          expect.objectContaining({
            status: "connecting",
            initialPrompt,
          }),
        );
        expect(mockTrpcAgent.start.mutate).not.toHaveBeenCalled();

        await vi.advanceTimersByTimeAsync(30_000);
        expect(clearSpy).not.toHaveBeenCalled();
        expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
          expect.anything(),
          expect.objectContaining({ status: "error" }),
        );

        mockAuth.fetchAuthState.mockResolvedValue({
          status: "authenticated",
          bootstrapComplete: true,
          cloudRegion: "us",
          orgProjectsMap: {},
          currentOrgId: null,
          currentProjectId: 123,
          hasCodeAccess: true,
          needsScopeReauth: false,
        });

        await vi.advanceTimersByTimeAsync(10_000);
        await promise;

        expect(clearSpy).toHaveBeenCalledWith("task-123", "/repo");
      } finally {
        vi.useRealTimers();
      }
    });

    describe("auto-retry on connect failure", () => {
      const setupFailingConnect = () => {
        const createTaskRun = vi
          .fn()
          .mockRejectedValue(new Error("Internal error"));
        mockBuildAuthenticatedClient.mockReturnValue({
          ...mockAuthenticatedClient,
          createTaskRun,
          appendTaskRunLog: vi.fn(),
        });
        return { createTaskRun };
      };

      it("parks the session in 'connecting' and auto-retries via clearSessionError", async () => {
        vi.useFakeTimers();
        try {
          setupFailingConnect();
          const service = getSessionService();
          const clearSpy = vi
            .spyOn(service, "clearSessionError")
            .mockResolvedValue(undefined);

          const promise = service.connectToTask({
            task: createMockTask(),
            repoPath: "/repo",
          });

          await vi.advanceTimersByTimeAsync(0);
          expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
            expect.objectContaining({ status: "connecting" }),
          );

          await vi.advanceTimersByTimeAsync(10_000);
          await promise;

          expect(clearSpy).toHaveBeenCalledTimes(1);
          expect(clearSpy).toHaveBeenCalledWith("task-123", "/repo");
          expect(mockSessionStoreSetters.setSession).not.toHaveBeenCalledWith(
            expect.objectContaining({ status: "error" }),
          );
        } finally {
          vi.useRealTimers();
        }
      });

      it("flips to error after both auto-retries fail", async () => {
        vi.useFakeTimers();
        try {
          setupFailingConnect();
          const service = getSessionService();
          const clearSpy = vi
            .spyOn(service, "clearSessionError")
            .mockRejectedValue(new Error("retry failed"));
          mockSessionStoreSetters.getSessionByTaskId.mockReturnValue({
            taskRunId: "error-task-123",
            taskId: "task-123",
          });

          const promise = service.connectToTask({
            task: createMockTask(),
            repoPath: "/repo",
          });

          await vi.advanceTimersByTimeAsync(25_000);
          await promise;

          expect(clearSpy).toHaveBeenCalledTimes(2);
          expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
            "error-task-123",
            expect.objectContaining({
              status: "error",
              errorTitle: "Failed to connect",
              errorMessage: "retry failed",
            }),
          );
        } finally {
          vi.useRealTimers();
        }
      });

      it("stops retrying and sets disconnected when device goes offline", async () => {
        vi.useFakeTimers();
        try {
          setupFailingConnect();
          const service = getSessionService();
          const clearSpy = vi
            .spyOn(service, "clearSessionError")
            .mockResolvedValue(undefined);
          mockSessionStoreSetters.getSessionByTaskId.mockReturnValue({
            taskRunId: "error-task-123",
            taskId: "task-123",
          });

          const promise = service.connectToTask({
            task: createMockTask(),
            repoPath: "/repo",
          });

          await vi.advanceTimersByTimeAsync(0);
          mockGetIsOnline.mockReturnValue(false);
          await vi.advanceTimersByTimeAsync(10_000);
          await promise;

          expect(clearSpy).not.toHaveBeenCalled();
          expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
            "error-task-123",
            expect.objectContaining({
              status: "disconnected",
              errorMessage: expect.stringContaining("No internet connection"),
            }),
          );
        } finally {
          vi.useRealTimers();
        }
      });

      it("skips final update when session was dismissed during retry gap", async () => {
        vi.useFakeTimers();
        try {
          setupFailingConnect();
          const service = getSessionService();
          const clearSpy = vi
            .spyOn(service, "clearSessionError")
            .mockRejectedValue(new Error("retry failed"));
          mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);

          const promise = service.connectToTask({
            task: createMockTask(),
            repoPath: "/repo",
          });

          await vi.advanceTimersByTimeAsync(25_000);
          await promise;

          expect(clearSpy).toHaveBeenCalled();
          expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalled();
        } finally {
          vi.useRealTimers();
        }
      });
    });
  });

  describe("disconnectFromTask", () => {
    it("does nothing if no session exists", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);

      await service.disconnectFromTask("task-123");

      expect(mockTrpcAgent.cancel.mutate).not.toHaveBeenCalled();
    });

    it("cancels agent and removes session", async () => {
      const service = getSessionService();
      const mockSession = createMockSession();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);

      await service.disconnectFromTask("task-123");

      expect(mockTrpcAgent.cancel.mutate).toHaveBeenCalledWith({
        sessionId: "run-123",
      });
      expect(mockSessionStoreSetters.removeSession).toHaveBeenCalledWith(
        "run-123",
      );
    });

    it("still removes session if cancel fails", async () => {
      const service = getSessionService();
      const mockSession = createMockSession();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockTrpcAgent.cancel.mutate.mockRejectedValue(new Error("Cancel failed"));

      await service.disconnectFromTask("task-123");

      expect(mockSessionStoreSetters.removeSession).toHaveBeenCalledWith(
        "run-123",
      );
    });
  });

  describe("watchCloudTask", () => {
    it("builds codex cloud mode options using native codex modes", () => {
      const service = getSessionService();

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        undefined,
        "full-access",
        "codex",
      );

      expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
        expect.objectContaining({
          configOptions: [
            expect.objectContaining({
              id: "mode",
              currentValue: "full-access",
              options: [
                expect.objectContaining({ value: "plan" }),
                expect.objectContaining({ value: "read-only" }),
                expect.objectContaining({ value: "auto" }),
                expect.objectContaining({ value: "full-access" }),
              ],
            }),
          ],
        }),
      );
    });

    it("keeps full-access after changing tasks and rebuilding the cloud session", async () => {
      let persistedConfigOptions: SessionConfigOption[] | undefined;
      mockSessionConfigStore.setPersistedConfigOptions.mockImplementation(
        (_taskRunId, options) => {
          persistedConfigOptions = options;
        },
      );
      mockSessionConfigStore.getPersistedConfigOptions.mockImplementation(
        () => persistedConfigOptions,
      );
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          adapter: "codex",
          cloudStatus: "in_progress",
          configOptions: [
            {
              id: "mode",
              name: "Approval Preset",
              type: "select",
              category: "mode",
              currentValue: "auto",
              options: [],
            },
            {
              id: "model",
              name: "Model",
              type: "select",
              category: "model",
              currentValue: "gpt-5.5",
              options: [],
            },
          ],
        }),
      );
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({ success: true });

      const initialService = getSessionService();
      await initialService.setSessionConfigOption(
        "task-123",
        "mode",
        "full-access",
      );
      expect(persistedConfigOptions).toEqual([
        expect.objectContaining({
          id: "mode",
          currentValue: "full-access",
        }),
        expect.objectContaining({
          id: "model",
          currentValue: "gpt-5.5",
        }),
      ]);

      resetSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);
      mockSessionStoreSetters.setSession.mockClear();
      const restoredService = getSessionService();
      restoredService.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.example.com",
        123,
        undefined,
        undefined,
        "auto",
        "codex",
      );

      expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
        expect.objectContaining({
          configOptions: expect.arrayContaining([
            expect.objectContaining({
              id: "mode",
              currentValue: "full-access",
            }),
            expect.objectContaining({
              id: "model",
              currentValue: "gpt-5.5",
            }),
          ]),
        }),
      );

      mockSessionConfigStore.getPersistedConfigOptions.mockReset();
      mockSessionConfigStore.getPersistedConfigOptions.mockReturnValue(
        undefined,
      );
      mockSessionConfigStore.setPersistedConfigOptions.mockReset();
    });

    it("drops persisted options when the cloud adapter changes", () => {
      const service = getSessionService();
      mockAdapterFns.getAdapter.mockReturnValue("claude");
      mockSessionConfigStore.getPersistedConfigOptions.mockReturnValue([
        {
          id: "mode",
          name: "Mode",
          type: "select",
          category: "mode",
          currentValue: "acceptEdits",
          options: [],
        },
        {
          id: "model",
          name: "Model",
          type: "select",
          category: "model",
          currentValue: "claude-opus-4-8",
          options: [],
        },
        {
          id: "effort",
          name: "Effort",
          type: "select",
          category: "thought_level",
          currentValue: "high",
          options: [],
        },
      ]);

      service.watchCloudTask(
        "task-adapter-change",
        "run-adapter-change",
        "https://api.example.com",
        123,
        undefined,
        undefined,
        "auto",
        "codex",
        "gpt-5.5",
        undefined,
        undefined,
        undefined,
        "max",
      );

      expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
        expect.objectContaining({
          adapter: "codex",
          configOptions: expect.arrayContaining([
            expect.objectContaining({
              category: "mode",
              currentValue: "auto",
            }),
            expect.objectContaining({
              category: "model",
              currentValue: "gpt-5.5",
            }),
            expect.objectContaining({
              category: "thought_level",
              currentValue: "max",
            }),
          ]),
        }),
      );
      const session = mockSessionStoreSetters.setSession.mock.calls.at(-1)?.[0];
      expect(session?.configOptions).not.toEqual(
        expect.arrayContaining([
          expect.objectContaining({ currentValue: "acceptEdits" }),
          expect.objectContaining({ currentValue: "claude-opus-4-8" }),
          expect.objectContaining({ id: "effort" }),
        ]),
      );
      expect(mockAdapterFns.setAdapter).toHaveBeenCalledWith(
        "run-adapter-change",
        "codex",
      );
    });

    it("shows the selected cloud model and reasoning before preview config loads", () => {
      const service = getSessionService();

      service.watchCloudTask(
        "task-runtime-123",
        "run-runtime-123",
        "https://api.example.com",
        7,
        undefined,
        undefined,
        "auto",
        "codex",
        "gpt-5.6-sol",
        undefined,
        undefined,
        undefined,
        "max",
      );

      expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
        expect.objectContaining({
          adapter: "codex",
          configOptions: expect.arrayContaining([
            expect.objectContaining({
              category: "model",
              currentValue: "gpt-5.6-sol",
            }),
            expect.objectContaining({
              category: "thought_level",
              currentValue: "max",
            }),
          ]),
        }),
      );
    });

    it("resets a same-run preloaded session before the first cloud snapshot", () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          taskRunId: "run-123",
          taskId: "task-123",
          taskTitle: "Cloud Task",
          events: [{ type: "acp_message", ts: 1, message: { method: "test" } }],
        }),
      );

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://app.example.com",
        2,
      );

      expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
        expect.objectContaining({
          taskRunId: "run-123",
          taskId: "task-123",
          taskTitle: "Cloud Task",
          isCloud: true,
          status: "disconnected",
          events: [],
        }),
      );
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ isCloud: true }),
      );
    });

    it("subscribes to cloud updates before starting the watcher", async () => {
      const service = getSessionService();

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );

      expect(mockTrpcCloudTask.onUpdate.subscribe).toHaveBeenCalledWith(
        { taskId: "task-123", runId: "run-123" },
        expect.objectContaining({
          onData: expect.any(Function),
          onError: expect.any(Function),
        }),
      );

      expect(mockTrpcCloudTask.watch.mutate).toHaveBeenCalledWith({
        taskId: "task-123",
        runId: "run-123",
        apiHost: "https://api.anthropic.com",
        teamId: 123,
      });

      expect(
        mockTrpcCloudTask.onUpdate.subscribe.mock.invocationCallOrder[0],
      ).toBeLessThan(
        mockTrpcCloudTask.watch.mutate.mock.invocationCallOrder[0],
      );
    });

    it("keeps the cloud watcher alive when the caller cleanup runs", () => {
      const service = getSessionService();
      const unsubscribe = vi.fn();
      mockTrpcCloudTask.onUpdate.subscribe.mockReturnValueOnce({
        unsubscribe,
      });

      const cleanup = service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );
      cleanup();

      expect(unsubscribe).not.toHaveBeenCalled();
      expect(mockTrpcCloudTask.unwatch.mutate).not.toHaveBeenCalled();
    });

    it("reuses the existing watcher across effect churn", () => {
      const service = getSessionService();
      const unsubscribe = vi.fn();
      mockTrpcCloudTask.onUpdate.subscribe.mockReturnValueOnce({
        unsubscribe,
      });

      const firstCleanup = service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );
      firstCleanup();
      const secondCleanup = service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );

      expect(unsubscribe).not.toHaveBeenCalled();
      expect(mockTrpcCloudTask.watch.mutate).toHaveBeenCalledTimes(1);

      secondCleanup();
      expect(unsubscribe).not.toHaveBeenCalled();
    });

    it("marks a reused same-run watcher terminal when task data reports completion", () => {
      const service = getSessionService();
      const unsubscribe = vi.fn();
      const onStatusChange = vi.fn();
      mockTrpcCloudTask.onUpdate.subscribe.mockReturnValueOnce({
        unsubscribe,
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        onStatusChange,
      );
      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://example.com/logs/run-123",
        undefined,
        "claude",
        undefined,
        undefined,
        undefined,
        "completed",
      );

      expect(mockSessionStoreSetters.updateCloudStatus).toHaveBeenCalledWith(
        "run-123",
        { status: "completed" },
      );
      expect(unsubscribe).toHaveBeenCalledTimes(1);
      expect(mockTrpcCloudTask.watch.mutate).toHaveBeenCalledTimes(1);
      expect(onStatusChange).not.toHaveBeenCalled();
    });

    it.each<[string, Partial<AgentSession>, boolean]>([
      [
        "skips a hydrated terminal (completed) run",
        { cloudStatus: "completed", processedLineCount: 5 },
        false,
      ],
      [
        "skips a hydrated terminal (failed) run",
        { cloudStatus: "failed", processedLineCount: 5 },
        false,
      ],
      [
        "watches a terminal run that is not yet hydrated",
        { cloudStatus: "completed", processedLineCount: undefined },
        true,
      ],
      [
        "watches a hydrated run that is still in progress",
        { cloudStatus: "in_progress", processedLineCount: 5 },
        true,
      ],
      [
        "watches when the hydrated terminal session is for a different run",
        {
          taskRunId: "run-999",
          cloudStatus: "completed",
          processedLineCount: 5,
        },
        true,
      ],
    ])("watchCloudTask %s", (_name, sessionOverrides, shouldWatch) => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          taskId: "task-123",
          taskRunId: "run-123",
          ...sessionOverrides,
        }),
      );

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );

      expect(mockTrpcCloudTask.onUpdate.subscribe).toHaveBeenCalledTimes(
        shouldWatch ? 1 : 0,
      );
      expect(mockTrpcCloudTask.watch.mutate).toHaveBeenCalledTimes(
        shouldWatch ? 1 : 0,
      );
    });

    it("hydrates a caller-reported terminal run without watching it", async () => {
      const service = getSessionService();
      const onStatusChange = vi.fn();
      const session = createMockSession({
        taskId: "task-123",
        taskRunId: "run-123",
        cloudStatus: "in_progress",
        events: [
          {
            type: "acp_message",
            ts: 1700000000,
            message: {
              jsonrpc: "2.0",
              method: "session/update",
              params: {},
            },
          } as AcpMessage,
        ],
        isPromptPending: true,
        messageQueue: [
          {
            id: "queued-1",
            content: "follow up",
            queuedAt: 1700000001,
          },
        ],
        processedLineCount: 1,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": session,
      });
      const finalEntries = [
        { timestamp: "2024-01-01T00:00:00Z", notification: {} },
        { timestamp: "2024-01-01T00:01:00Z", notification: {} },
      ];
      const finalEvents = [
        {
          type: "acp_message",
          ts: 1700000000,
          message: {
            jsonrpc: "2.0",
            method: "session/update",
            params: {},
          },
        } as AcpMessage,
        {
          type: "acp_message",
          ts: 1700000001,
          message: {
            jsonrpc: "2.0",
            method: "session/update",
            params: {},
          },
        } as AcpMessage,
      ];
      mockAuthenticatedClient.getTaskRunSessionLogsResult.mockResolvedValue({
        entries: finalEntries,
        complete: true,
      });
      mockConvertStoredEntriesToEvents.mockReturnValueOnce(finalEvents);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        onStatusChange,
        "https://example.com/logs/run-123",
        undefined,
        "claude",
        undefined,
        undefined,
        undefined,
        "completed",
      );

      expect(mockSessionStoreSetters.updateCloudStatus).toHaveBeenCalledWith(
        "run-123",
        { status: "completed" },
      );
      expect(mockSessionStoreSetters.clearMessageQueue).toHaveBeenCalledWith(
        "task-123",
      );
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ isPromptPending: false }),
      );

      expect(mockTrpcCloudTask.onUpdate.subscribe).not.toHaveBeenCalled();
      expect(mockTrpcCloudTask.watch.mutate).not.toHaveBeenCalled();
      expect(onStatusChange).not.toHaveBeenCalled();
      await vi.waitFor(() => {
        expect(
          mockAuthenticatedClient.getTaskRunSessionLogsResult,
        ).toHaveBeenCalledWith("task-123", "run-123", { limit: 100000 });
      });
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({
          events: finalEvents,
          processedLineCount: finalEntries.length,
        }),
      );
    });

    it("falls back to the run log URL when terminal chain hydration is empty", async () => {
      const service = getSessionService();
      const session = createMockSession({
        taskId: "task-123",
        taskRunId: "run-123",
        cloudStatus: "in_progress",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": session,
      });
      mockAuthenticatedClient.getTaskRunSessionLogs.mockResolvedValue([]);
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue(
        JSON.stringify({
          type: "notification",
          timestamp: "2024-01-01T00:00:00Z",
          notification: {
            method: "session/update",
            params: {},
          },
        }),
      );
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);
      const finalEvents = [
        {
          type: "acp_message",
          ts: 1700000000,
          message: {
            jsonrpc: "2.0",
            method: "session/update",
            params: {},
          },
        } as AcpMessage,
      ];
      mockConvertStoredEntriesToEvents.mockReturnValueOnce(finalEvents);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://example.com/logs/run-123",
        undefined,
        "claude",
        undefined,
        "build me a thing",
        undefined,
        "completed",
      );

      await vi.waitFor(() => {
        expect(mockTrpcLogs.fetchS3Logs.query).toHaveBeenCalledWith({
          logUrl: "https://example.com/logs/run-123",
        });
      });
      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            events: finalEvents,
            processedLineCount: 1,
          }),
        );
      });
      expect(
        mockSessionStoreSetters.clearTailOptimisticItems,
      ).toHaveBeenCalledWith("run-123");
      expect(
        mockSessionStoreSetters.appendOptimisticItem,
      ).not.toHaveBeenCalled();
    });

    it("does not cache or seed an empty terminal hydration", async () => {
      const service = getSessionService();
      const session = createMockSession({
        taskId: "task-123",
        taskRunId: "run-123",
        cloudStatus: "in_progress",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": session,
      });
      mockAuthenticatedClient.getTaskRunSessionLogs.mockResolvedValue([]);
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://example.com/logs/run-123",
        undefined,
        "claude",
        undefined,
        "build me a thing",
        undefined,
        "completed",
      );

      await vi.waitFor(() => {
        expect(
          mockSessionStoreSetters.clearTailOptimisticItems,
        ).toHaveBeenCalledWith("run-123");
      });
      expect(
        mockSessionStoreSetters.appendOptimisticItem,
      ).not.toHaveBeenCalled();
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ processedLineCount: 0 }),
      );
    });

    it("starts terminal hydration even when resume-chain hydration is already in flight", async () => {
      const service = getSessionService();
      const session = createMockSession({
        taskId: "task-123",
        taskRunId: "run-123",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": session,
      });
      let resolveFirstHydration!: (result: {
        entries: Array<{ timestamp: string; notification: object }>;
        complete: boolean;
      }) => void;
      const firstHydration = new Promise<{
        entries: Array<{ timestamp: string; notification: object }>;
        complete: boolean;
      }>((resolve) => {
        resolveFirstHydration = resolve;
      });
      mockAuthenticatedClient.getTaskRunSessionLogsResult
        .mockReturnValueOnce(firstHydration)
        .mockResolvedValueOnce({ entries: [], complete: true });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://example.com/logs/run-123",
        undefined,
        "claude",
        undefined,
        undefined,
        undefined,
        "in_progress",
        undefined,
        { resume_from_run_id: "previous-run" },
      );

      // Resume hydration fetches the ancestor and current run in parallel;
      // the pending ancestor fetch keeps this first hydration in flight.
      await vi.waitFor(() => {
        expect(
          mockAuthenticatedClient.getTaskRunSessionLogsResult,
        ).toHaveBeenCalledTimes(2);
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://example.com/logs/run-123",
        undefined,
        "claude",
        undefined,
        undefined,
        undefined,
        "completed",
        undefined,
        { resume_from_run_id: "previous-run" },
      );

      // The terminal hydration issues its own single terminal-chain fetch
      // instead of being deduped onto the in-flight resume-chain hydration.
      await vi.waitFor(() => {
        expect(
          mockAuthenticatedClient.getTaskRunSessionLogsResult,
        ).toHaveBeenCalledTimes(3);
      });
      resolveFirstHydration({ entries: [], complete: true });
    });

    it("keeps the settled terminal cursor when a resume-chain hydration resolves late", async () => {
      const service = getSessionService();
      const session = createMockSession({
        taskId: "task-123",
        taskRunId: "run-123",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": session,
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");
      const entry = (text: string) => ({
        timestamp: "2026-07-15T10:00:00+00:00",
        notification: {
          method: "session/update",
          params: {
            update: {
              sessionUpdate: "agent_message",
              content: { type: "text", text },
            },
          },
        },
      });
      let resolveAncestor!: (r: {
        entries: object[];
        complete: boolean;
      }) => void;
      let resolveCurrent!: (r: {
        entries: object[];
        complete: boolean;
      }) => void;
      mockAuthenticatedClient.getTaskRunSessionLogsResult
        .mockReturnValueOnce(
          new Promise((r) => {
            resolveAncestor = r;
          }),
        )
        .mockReturnValueOnce(
          new Promise((r) => {
            resolveCurrent = r;
          }),
        );

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://example.com/logs/run-123",
        undefined,
        "claude",
        undefined,
        undefined,
        undefined,
        "in_progress",
        undefined,
        { resume_from_run_id: "previous-run" },
      );

      await vi.waitFor(() => {
        expect(
          mockAuthenticatedClient.getTaskRunSessionLogsResult,
        ).toHaveBeenCalledTimes(2);
      });

      // The run settles while the resume-chain fetches are still in flight,
      // exactly as a concurrent terminal-chain hydration records it.
      session.cloudStatus = "completed";
      session.processedLineCount = 5;

      resolveAncestor({ entries: [entry("a"), entry("b")], complete: true });
      resolveCurrent({ entries: [entry("c")], complete: true });

      // The late resume-chain write must not lower the settled cursor to its
      // leaf-only count.
      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({ processedLineCount: 5 }),
        );
      });
    });

    it("does not re-subscribe across repeated calls for a hydrated terminal run", () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          taskId: "task-123",
          taskRunId: "run-123",
          cloudStatus: "completed",
          processedLineCount: 5,
        }),
      );

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );
      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );

      expect(mockTrpcCloudTask.onUpdate.subscribe).not.toHaveBeenCalled();
      expect(mockTrpcCloudTask.watch.mutate).not.toHaveBeenCalled();
    });

    it("preserves an existing status callback when reusing a watcher without one", () => {
      const service = getSessionService();
      const onStatusChange = vi.fn();

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        onStatusChange,
      );
      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      expect(onStatusChange).toHaveBeenCalledTimes(1);
    });

    it("ignores stale non-terminal stream status after a terminal status", () => {
      const service = getSessionService();
      const onStatusChange = vi.fn();
      const completedSession = createMockSession({
        taskId: "task-123",
        taskRunId: "run-123",
        isCloud: true,
        cloudStatus: "completed",
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": completedSession,
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        onStatusChange,
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      expect(mockSessionStoreSetters.updateCloudStatus).not.toHaveBeenCalled();
      expect(onStatusChange).not.toHaveBeenCalled();
    });

    it("hydrates a fresh cloud session from persisted logs before replay arrives", async () => {
      const service = getSessionService();
      const hydratedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        taskTitle: "Cloud Task",
        status: "disconnected",
        isCloud: true,
        events: [],
      });

      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(() => {
        return hydratedSession;
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue(
        JSON.stringify({
          type: "notification",
          timestamp: "2024-01-01T00:00:00Z",
          notification: {
            method: "session/update",
            params: {
              update: {
                sessionUpdate: "assistant_message",
              },
            },
          },
        }),
      );
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            events: [],
            isCloud: true,
            logUrl: "https://logs.example.com/run-123",
            processedLineCount: 1,
          }),
        );
      });
    });

    it("flips isPromptPending on hydration when the log tail has an in-flight prompt", async () => {
      const service = getSessionService();
      const hydratedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        hydratedSession,
      );
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      const inFlightPrompt = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          id: 42,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "hi" }] },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([inFlightPrompt]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            isPromptPending: true,
            promptStartedAt: inFlightPrompt.ts,
            currentPromptId: 42,
          }),
        );
      });
    });

    it("leaves isPromptPending false on hydration when the log tail has a completed prompt", async () => {
      const service = getSessionService();
      const hydratedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        hydratedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": { ...hydratedSession, currentPromptId: 42 },
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      const promptRequest = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          id: 42,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "hi" }] },
        },
      };
      const promptResponse = {
        type: "acp_message" as const,
        ts: 1700000005,
        message: {
          jsonrpc: "2.0" as const,
          id: 42,
          result: { stopReason: "end_turn" },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([
        promptRequest,
        promptResponse,
      ]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            isPromptPending: false,
          }),
        );
      });
      // The response must not disarm the turn: `_posthog/turn_complete` is the
      // cloud turn-done signal and still needs currentPromptId to notify.
      const disarmed = mockSessionStoreSetters.updateSession.mock.calls.some(
        (call) =>
          call[0] === "run-123" &&
          (call[1] as Record<string, unknown> | undefined)?.currentPromptId ===
            null,
      );
      expect(disarmed).toBe(false);
    });

    it("flushes queued cloud messages on _posthog/turn_complete", async () => {
      const service = getSessionService();
      // Reset auth client (a prior test may have set it to null).
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      const sessionWithQueue = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        cloudStatus: "in_progress",
        events: [],
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        sessionWithQueue,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": sessionWithQueue,
      });
      mockSessionStoreSetters.dequeueMessages.mockReturnValue([queuedMessage]);
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
        result: { stopReason: "end_turn" },
      });

      const turnCompleteEvent = {
        type: "acp_message" as const,
        ts: 1700000001,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: { sessionId: "acp-session", stopReason: "end_turn" },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([turnCompleteEvent]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
          expect.objectContaining({
            taskId: "task-123",
            method: "user_message",
            params: expect.objectContaining({ content: "follow up" }),
          }),
        );
      });
    });

    it("flushes queued cloud messages when cloudStatus flips to in_progress on a connected, idle session", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      // `agentIdleForRunId` proves a turn_complete fired for THIS run.
      // Without it, a connected-but-mid-boot session would race the
      // initial/resume turn — the recovery helper must not drain.
      const sessionWithQueue = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        cloudStatus: "in_progress",
        events: [],
        agentIdleForRunId: "run-123",
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        sessionWithQueue,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": sessionWithQueue,
      });
      mockSessionStoreSetters.dequeueMessages.mockReturnValue([queuedMessage]);
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
        result: { stopReason: "end_turn" },
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
          expect.objectContaining({
            taskId: "task-123",
            method: "user_message",
            params: expect.objectContaining({ content: "follow up" }),
          }),
        );
      });
    });

    it("coalesces repeated idle recovery status updates before the queued flush runs", () => {
      const service = getSessionService();
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      let messageReads = 0;
      const runStartedEvent = {
        type: "acp_message" as const,
        ts: 1700000000,
        get message() {
          messageReads += 1;
          return {
            jsonrpc: "2.0" as const,
            method: "_posthog/run_started",
            params: { runId: "run-123", taskId: "task-123" },
          };
        },
      } as AcpMessage;
      const turnCompleteEvent = {
        type: "acp_message" as const,
        ts: 1700000001,
        get message() {
          messageReads += 1;
          return {
            jsonrpc: "2.0" as const,
            method: "_posthog/turn_complete",
            params: { sessionId: "acp-session", stopReason: "end_turn" },
          };
        },
      } as AcpMessage;
      const sessionWithQueue = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        cloudStatus: "in_progress",
        agentIdleForRunId: undefined,
        events: [runStartedEvent, turnCompleteEvent],
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        sessionWithQueue,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": sessionWithQueue,
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };

      vi.useFakeTimers();
      try {
        for (let i = 0; i < 100; i += 1) {
          subscribeOptions.onData({
            kind: "status",
            taskId: "task-123",
            runId: "run-123",
            status: "in_progress",
          });
        }

        // The two reads are the initial incremental scan over
        // run_started/turn_complete; repeated in_progress updates must not
        // re-read the same historical events.
        expect(messageReads).toBe(2);
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          { agentIdleForRunId: "run-123" },
        );
      } finally {
        vi.clearAllTimers();
        vi.useRealTimers();
      }
    });

    it("does not flush queued cloud messages when cloudStatus flips to in_progress while still connecting", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      const sessionWithQueue = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connecting",
        isCloud: true,
        cloudStatus: "queued",
        events: [],
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        sessionWithQueue,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": sessionWithQueue,
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      // Give the setTimeout(0) microtask time to resolve had it been scheduled.
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
    });

    it("re-enqueues queued cloud messages when the dispatch fails", async () => {
      const service = getSessionService();
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      const sessionWithQueue = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        cloudStatus: "in_progress",
        events: [],
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        sessionWithQueue,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": sessionWithQueue,
      });
      mockSessionStoreSetters.dequeueMessages.mockReturnValue([queuedMessage]);
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);
      mockTrpcCloudTask.sendCommand.mutate.mockRejectedValue(
        new Error("transient backend failure"),
      );

      const turnCompleteEvent = {
        type: "acp_message" as const,
        ts: 1700000001,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: { sessionId: "acp-session", stopReason: "end_turn" },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([turnCompleteEvent]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      await vi.waitFor(() => {
        expect(
          mockSessionStoreSetters.prependQueuedMessages,
        ).toHaveBeenCalledWith("task-123", [queuedMessage]);
      });
    });

    it("upgrades status to connected on turn_complete when run_started was never received", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      // Session starts disconnected — simulates an old agent that never
      // emitted _posthog/run_started.
      const sessionWithQueue = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        cloudStatus: "in_progress",
        events: [],
        messageQueue: [queuedMessage],
      });
      // After the turn_complete handler flips status to "connected",
      // sendQueuedCloudMessages reads the session again via
      // getSessionByTaskId. We return the disconnected version first
      // (for the turn_complete handler) then the connected version
      // (for the queue dispatcher's canSendNow check).
      const connectedSession = createMockSession({
        ...sessionWithQueue,
        status: "connected",
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": sessionWithQueue,
      });
      mockSessionStoreSetters.getSessionByTaskId
        .mockReturnValueOnce(sessionWithQueue)
        .mockReturnValue(connectedSession);
      mockSessionStoreSetters.dequeueMessages.mockReturnValue([queuedMessage]);
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
        result: { stopReason: "end_turn" },
      });

      const turnCompleteEvent = {
        type: "acp_message" as const,
        ts: 1700000001,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: { sessionId: "acp-session", stopReason: "end_turn" },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([turnCompleteEvent]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          { status: "connected", agentIdleForRunId: "run-123" },
        );
      });

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
          expect.objectContaining({
            taskId: "task-123",
            method: "user_message",
            params: expect.objectContaining({ content: "follow up" }),
          }),
        );
      });
    });

    it("recovers a disconnected idle resumed run and drains the queue on an in_progress status update", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      // The agent already booted/turn-completed for this exact run, then an
      // SSE transport drop (or the retry it triggers) flipped the session to
      // "disconnected". No fresh run_started/turn_complete will ever arrive
      // for the idle run.
      const disconnectedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        cloudStatus: "in_progress",
        isPromptPending: false,
        agentIdleForRunId: "run-123",
        events: [],
        messageQueue: [queuedMessage],
      });
      const connectedSession = createMockSession({
        ...disconnectedSession,
        status: "connected",
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": disconnectedSession,
      });
      // The recovery path reads via getSessions (disconnected); the queue
      // dispatcher then reads via getSessionByTaskId after status is flipped.
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        connectedSession,
      );
      mockSessionStoreSetters.dequeueMessages.mockReturnValue([queuedMessage]);
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
        result: { stopReason: "end_turn" },
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          {
            status: "connected",
            errorTitle: undefined,
            errorMessage: undefined,
          },
        );
      });
      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
          expect.objectContaining({
            taskId: "task-123",
            method: "user_message",
            params: expect.objectContaining({ content: "follow up" }),
          }),
        );
      });
    });

    it("recovers a disconnected run from a current-run run_started + turn_complete when the live flag was lost", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      // No live `agentIdleForRunId` (session recreated from logs and the
      // no-delta dedup guard skipped reprocessing), but THIS run's
      // run_started followed by a turn_complete is still in events — a
      // completed turn for the current run, so the agent is idle.
      const runStartedEvent = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/run_started",
          params: {
            sessionId: "acp-session",
            runId: "run-123",
            taskId: "task-123",
            agentVersion: "2.3.556",
          },
        },
      };
      const turnCompleteEvent = {
        type: "acp_message" as const,
        ts: 1700000001,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: { sessionId: "acp-session", stopReason: "end_turn" },
        },
      };
      const disconnectedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        cloudStatus: "in_progress",
        isPromptPending: false,
        agentIdleForRunId: undefined,
        events: [runStartedEvent, turnCompleteEvent],
        messageQueue: [queuedMessage],
      });
      const connectedSession = createMockSession({
        ...disconnectedSession,
        status: "connected",
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": disconnectedSession,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        connectedSession,
      );
      mockSessionStoreSetters.dequeueMessages.mockReturnValue([queuedMessage]);
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
        result: { stopReason: "end_turn" },
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
          expect.objectContaining({
            taskId: "task-123",
            method: "user_message",
            params: expect.objectContaining({ content: "follow up" }),
          }),
        );
      });
    });

    it("restores idle evidence after a failed queued dispatch so recovery can retry", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      const runStartedEvent = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/run_started",
          params: {
            sessionId: "acp-session",
            runId: "run-123",
            taskId: "task-123",
          },
        },
      };
      const turnCompleteEvent = {
        type: "acp_message" as const,
        ts: 1700000001,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: { sessionId: "acp-session", stopReason: "end_turn" },
        },
      };
      const disconnectedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        cloudStatus: "in_progress",
        isPromptPending: false,
        agentIdleForRunId: undefined,
        events: [runStartedEvent, turnCompleteEvent],
        messageQueue: [queuedMessage],
      });
      const connectedSession = createMockSession({
        ...disconnectedSession,
        status: "connected",
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": disconnectedSession,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        connectedSession,
      );
      mockSessionStoreSetters.dequeueMessages.mockReturnValue([queuedMessage]);
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);
      mockTrpcCloudTask.sendCommand.mutate
        .mockRejectedValueOnce(new Error("transient backend failure"))
        .mockResolvedValueOnce({
          success: true,
          result: { stopReason: "end_turn" },
        });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledTimes(1);
      });
      await vi.waitFor(() => {
        expect(
          mockSessionStoreSetters.prependQueuedMessages,
        ).toHaveBeenCalledWith("task-123", [queuedMessage]);
      });

      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledTimes(2);
      });
    });

    it("does not recover a disconnected run when boot evidence is from a different run id", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      // run_started belongs to a PREVIOUS run — must not be mistaken for the
      // new run's boot after a resume.
      const staleRunStartedEvent = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/run_started",
          params: {
            sessionId: "acp-session",
            runId: "old-run",
            taskId: "task-123",
            agentVersion: "2.3.556",
          },
        },
      };
      const disconnectedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        cloudStatus: "in_progress",
        isPromptPending: false,
        agentIdleForRunId: undefined,
        events: [staleRunStartedEvent],
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        disconnectedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": disconnectedSession,
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
    });

    it("does not recover from a carried-over prior-run turn_complete", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      // Resume copies the PREVIOUS run's history into the new run's
      // session. The prior run's run_started + turn_complete must not make
      // the new run look idle before its own resume turn completes.
      const priorRunStarted = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/run_started",
          params: { sessionId: "old", runId: "old-run", taskId: "task-123" },
        },
      };
      const priorTurnComplete = {
        type: "acp_message" as const,
        ts: 1700000001,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: { sessionId: "old", stopReason: "end_turn" },
        },
      };
      const disconnectedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        cloudStatus: "in_progress",
        isPromptPending: false,
        agentIdleForRunId: undefined,
        events: [priorRunStarted, priorTurnComplete],
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        disconnectedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": disconnectedSession,
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      // The recovery branch flips status -> connected; assert it never fired
      // (sendCommand alone is insufficient — the mocked store would bail the
      // drain on the stale disconnected status regardless).
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ status: "connected" }),
      );
    });

    it("does not recover when the current run started but its turn has not completed", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      // Prior-run history + the current run's run_started, but no
      // turn_complete for the current run yet (resume turn still running).
      const priorTurnComplete = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: { sessionId: "old", stopReason: "end_turn" },
        },
      };
      const currentRunStarted = {
        type: "acp_message" as const,
        ts: 1700000001,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/run_started",
          params: { sessionId: "new", runId: "run-123", taskId: "task-123" },
        },
      };
      const disconnectedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        cloudStatus: "in_progress",
        isPromptPending: false,
        agentIdleForRunId: undefined,
        events: [priorTurnComplete, currentRunStarted],
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        disconnectedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": disconnectedSession,
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ status: "connected" }),
      );
    });

    it("does not recover a disconnected run while a prompt is in flight", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      const disconnectedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        cloudStatus: "in_progress",
        isPromptPending: true,
        agentIdleForRunId: "run-123",
        events: [],
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        disconnectedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": disconnectedSession,
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ status: "connected" }),
      );
    });

    it("does not recover a still-booting disconnected run with no boot evidence", async () => {
      const service = getSessionService();
      mockBuildAuthenticatedClient.mockReturnValue(mockAuthenticatedClient);
      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      // Fresh boot: no run_started for this run yet, no live flag. Draining
      // now would race sendInitialTaskMessage/sendResumeMessage.
      const bootingSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        cloudStatus: "in_progress",
        isPromptPending: false,
        agentIdleForRunId: undefined,
        events: [],
        messageQueue: [queuedMessage],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        bootingSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": bootingSession,
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: {
          kind: "status";
          taskId: string;
          runId: string;
          status: "in_progress";
        }) => void;
      };
      subscribeOptions.onData({
        kind: "status",
        taskId: "task-123",
        runId: "run-123",
        status: "in_progress",
      });

      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ status: "connected" }),
      );
    });

    it("clears isPromptPending from structured turn completion logs on hydration", async () => {
      const service = getSessionService();
      const hydratedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        hydratedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": { ...hydratedSession, currentPromptId: 42 },
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      const promptRequest = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          id: 42,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "hi" }] },
        },
      };
      const completion = {
        type: "acp_message" as const,
        ts: 1700000005,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: {
            sessionId: "session-1",
            stopReason: "end_turn",
          },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([
        promptRequest,
        completion,
      ]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            isPromptPending: false,
            promptStartedAt: null,
            currentPromptId: null,
          }),
        );
      });
    });

    it("reconciles cloud log gaps from persisted logs", async () => {
      const service = getSessionService();
      const existingSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        logUrl: "https://logs.example.com/run-123",
        processedLineCount: 5,
        events: [
          {
            type: "acp_message",
            ts: 1,
            message: { method: "existing" },
          },
        ],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        existingSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": existingSession,
      });

      const storedLine = JSON.stringify({
        type: "notification",
        timestamp: "2024-01-01T00:00:00Z",
        notification: {
          method: "session/update",
          params: { update: { sessionUpdate: "assistant_message" } },
        },
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue(
        Array.from({ length: 14 }, () => storedLine).join("\n"),
      );

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );
      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: unknown) => void;
      };

      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-123",
        totalEntryCount: 14,
        newEntries: [
          {
            type: "notification",
            timestamp: "2024-01-01T00:00:01Z",
            notification: {
              method: "session/update",
              params: { update: { sessionUpdate: "assistant_message" } },
            },
          },
        ],
      });

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            events: [],
            isCloud: true,
            logUrl: "https://logs.example.com/run-123",
            processedLineCount: 14,
          }),
        );
      });
      expect(mockSessionStoreSetters.appendEvents).not.toHaveBeenCalled();
    });

    it("falls back to remote logs when local gap repair cache is stale", async () => {
      const service = getSessionService();
      const existingSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        logUrl: "https://logs.example.com/run-123",
        processedLineCount: 5,
        events: [
          {
            type: "acp_message",
            ts: 1,
            message: { method: "existing" },
          },
        ],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        existingSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": existingSession,
      });

      const storedLine = JSON.stringify({
        type: "notification",
        timestamp: "2024-01-01T00:00:00Z",
        notification: {
          method: "session/update",
          params: { update: { sessionUpdate: "assistant_message" } },
        },
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue(
        Array.from({ length: 5 }, () => storedLine).join("\n"),
      );
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue(
        Array.from({ length: 14 }, () => storedLine).join("\n"),
      );

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );
      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: unknown) => void;
      };

      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-123",
        totalEntryCount: 14,
        newEntries: [
          {
            type: "notification",
            timestamp: "2024-01-01T00:00:01Z",
            notification: {
              method: "session/update",
              params: { update: { sessionUpdate: "assistant_message" } },
            },
          },
        ],
      });

      await vi.waitFor(() => {
        expect(mockTrpcLogs.fetchS3Logs.query).toHaveBeenCalledWith({
          logUrl: "https://logs.example.com/run-123",
        });
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            processedLineCount: 14,
          }),
        );
      });
      expect(mockSessionStoreSetters.appendEvents).not.toHaveBeenCalled();
    });

    it("queues a pending cloud log gap when stale fetches can't fill it, without appending", async () => {
      const service = getSessionService();
      let sessionState = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        logUrl: "https://logs.example.com/run-123",
        processedLineCount: 5,
        events: [
          {
            type: "acp_message",
            ts: 1,
            message: { method: "existing" },
          },
        ],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        () => sessionState,
      );
      mockSessionStoreSetters.getSessions.mockImplementation(() => ({
        "run-123": sessionState,
      }));
      mockSessionStoreSetters.appendEvents.mockImplementation(
        (_taskRunId, events, processedLineCount) => {
          sessionState = {
            ...sessionState,
            events: [...sessionState.events, ...events],
            processedLineCount,
          };
        },
      );

      let resolveFirstLocalLogs!: (content: string) => void;
      mockTrpcLogs.readLocalLogs.query
        .mockImplementationOnce(
          () =>
            new Promise<string>((resolve) => {
              resolveFirstLocalLogs = resolve;
            }),
        )
        .mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");
      mockConvertStoredEntriesToEvents.mockImplementation((entries) =>
        entries.map((entry, index) => ({
          type: "acp_message",
          ts: index,
          message: {
            jsonrpc: "2.0",
            method: "session/update",
            params: { entry },
          },
        })),
      );

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );
      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: unknown) => void;
      };
      const firstEntry = {
        type: "notification",
        timestamp: "2024-01-01T00:00:01Z",
        notification: { method: "session/update" },
      };
      const secondEntry = {
        type: "notification",
        timestamp: "2024-01-01T00:00:02Z",
        notification: { method: "session/update" },
      };
      const thirdEntry = {
        type: "notification",
        timestamp: "2024-01-01T00:00:03Z",
        notification: { method: "session/update" },
      };

      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-123",
        totalEntryCount: 14,
        newEntries: [firstEntry],
      });
      await vi.waitFor(() => {
        expect(mockTrpcLogs.readLocalLogs.query).toHaveBeenCalledTimes(1);
      });

      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-123",
        totalEntryCount: 16,
        newEntries: [secondEntry, thirdEntry],
      });
      resolveFirstLocalLogs("");

      // The pending request must drain after the in-flight one resolves —
      // verify the second readLocalLogs call eventually happens.
      await vi.waitFor(() => {
        expect(mockTrpcLogs.readLocalLogs.query).toHaveBeenCalledTimes(2);
      });
      // Stale fetches can't fill the gap; we must NOT append the snapshot's
      // tail slice (positions [expectedCount-N, expectedCount]) on top of an
      // events array that's still at processedLineCount=5 — that path used
      // to corrupt the array with duplicates/gaps and ratchet
      // processedLineCount past entries we don't actually have, leading to
      // unbounded growth on long-running cloud runs.
      expect(mockSessionStoreSetters.appendEvents).not.toHaveBeenCalled();
    });

    const setupReconcileLoopTest = (logContent: string) => {
      const service = getSessionService();
      const existingSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        logUrl: "https://logs.example.com/run-123",
        processedLineCount: 5,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        existingSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": existingSession,
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue(logContent);
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue(logContent);
      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );
      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as {
        onData: (update: unknown) => void;
      };
      return { subscribeOptions };
    };

    const newEntry = {
      type: "notification",
      timestamp: "2024-01-01T00:00:01Z",
      notification: { method: "session/update" },
    };
    const validLine = JSON.stringify({
      type: "notification",
      timestamp: "2024-01-01T00:00:00Z",
      notification: { method: "session/update" },
    });

    it("breaks the reconcile loop on first observation when parse failures are present", async () => {
      const { subscribeOptions } = setupReconcileLoopTest(
        [
          ...Array.from({ length: 8 }, () => validLine),
          "}}not-json{{",
          "{broken",
        ].join("\n"),
      );

      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-123",
        totalEntryCount: 20,
        newEntries: [newEntry],
      });

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({ processedLineCount: 20 }),
        );
      });
    });

    it("breaks the reconcile loop after a repeated stable deficiency", async () => {
      const { subscribeOptions } = setupReconcileLoopTest(
        Array.from({ length: 8 }, () => validLine).join("\n"),
      );

      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-123",
        totalEntryCount: 14,
        newEntries: [newEntry],
      });
      await vi.waitFor(() => {
        expect(mockTrpcLogs.fetchS3Logs.query).toHaveBeenCalledTimes(1);
      });

      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ processedLineCount: 14 }),
      );

      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-123",
        totalEntryCount: 14,
        newEntries: [newEntry],
      });

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({ processedLineCount: 14 }),
        );
      });
    });

    it("flips status to connected on _posthog/run_started", async () => {
      const service = getSessionService();
      const hydratedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        hydratedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": hydratedSession,
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      const runStartedEvent = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/run_started",
          params: {
            sessionId: "acp-session",
            runId: "run-123",
            taskId: "task-123",
          },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([runStartedEvent]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          { status: "connected" },
        );
      });
      // run_started must NOT mark the agent idle — the resume/initial turn
      // starts right after it.
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ agentIdleForRunId: "run-123" }),
      );
    });

    it("captures agent capabilities from run_started params onto the session", async () => {
      const service = getSessionService();
      const hydratedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        hydratedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": hydratedSession,
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      const runStartedEvent = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/run_started",
          params: {
            sessionId: "acp-session",
            runId: "run-123",
            taskId: "task-123",
            agentVersion: "0.42.3",
            steering: "native",
          },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([runStartedEvent]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            agentVersion: "0.42.3",
            steering: "native",
            status: "connected",
          }),
        );
      });
    });

    it("does not re-flip status when run_started arrives but session is already connected", async () => {
      const service = getSessionService();
      const connectedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        connectedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": connectedSession,
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("{}");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      const runStartedEvent = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/run_started",
          params: {
            sessionId: "acp-session",
            runId: "run-123",
            taskId: "task-123",
          },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([runStartedEvent]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
      );

      // Wait long enough for the hydration callback to run; assert the
      // store was never told to set status: "connected" again.
      await new Promise((resolve) => setTimeout(resolve, 100));
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        { status: "connected" },
      );
    });

    it("seeds an optimistic user-message when hydrating a brand-new task with no prior history", async () => {
      const service = getSessionService();
      const freshSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(freshSession);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": freshSession,
      });
      // Empty history — fetchSessionLogs returns no entries.
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
        undefined,
        "claude",
        undefined,
        "build me a thing",
      );

      await vi.waitFor(() => {
        expect(
          mockSessionStoreSetters.appendOptimisticItem,
        ).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            type: "user_message",
            content: "build me a thing",
          }),
        );
      });
    });

    it("seeds an optimistic user-message when persisted entries exist but no session/prompt yet (agent emitted lifecycle notifications first)", async () => {
      const service = getSessionService();
      const freshSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(freshSession);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": freshSession,
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue(
        JSON.stringify({
          jsonrpc: "2.0",
          method: "_posthog/run_started",
          params: {
            sessionId: "acp-session-1",
            runId: "run-123",
            taskId: "task-123",
          },
        }),
      );
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      // Lifecycle notification only — no session/prompt request yet.
      const lifecycleNotification = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/run_started",
          params: {
            sessionId: "acp-session-1",
            runId: "run-123",
            taskId: "task-123",
          },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([
        lifecycleNotification,
      ]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
        undefined,
        "claude",
        undefined,
        "build me a thing",
      );

      await vi.waitFor(() => {
        expect(
          mockSessionStoreSetters.appendOptimisticItem,
        ).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({
            type: "user_message",
            content: "build me a thing",
          }),
        );
      });
    });

    it("restores a pending question from terminal cloud-run logs after restart", async () => {
      const service = getSessionService();
      const completedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        events: [
          {
            type: "acp_message",
            ts: 1700000000,
            message: {
              jsonrpc: "2.0",
              method: "session/update",
              params: { update: { sessionUpdate: "tool_call" } },
            },
          } as AcpMessage,
        ],
        cloudStatus: "completed",
        processedLineCount: 3,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        completedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": completedSession,
      });
      mockAuthenticatedClient.getTaskRunSessionLogsResult.mockResolvedValue({
        complete: true,
        entries: [
          {
            type: "notification",
            notification: {
              method: "_posthog/sdk_session",
              params: {
                taskRunId: "run-123",
                sessionId: "acp-session-1",
                adapter: "claude",
              },
            },
          },
          {
            type: "notification",
            notification: {
              method: "_posthog/run_started",
              params: {
                sessionId: "acp-session-1",
                runId: "run-123",
                taskId: "task-123",
              },
            },
          },
          {
            type: "notification",
            notification: {
              method: "_posthog/permission_request",
              params: {
                requestId: "request-1",
                toolCall: {
                  toolCallId: "tool-1",
                  title: "What animal do you prefer?",
                  kind: "other",
                  _meta: {
                    codeToolKind: "question",
                    questions: [
                      {
                        question: "What animal do you prefer?",
                        options: [
                          { label: "cats", description: "Cats" },
                          { label: "dogs", description: "Dogs" },
                        ],
                      },
                    ],
                  },
                },
                options: [
                  { optionId: "option_0", name: "cats", kind: "allow_once" },
                  { optionId: "option_1", name: "dogs", kind: "allow_once" },
                ],
              },
            },
          },
        ],
      });

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
        undefined,
        "claude",
        undefined,
        "ask about animals",
        undefined,
        "completed",
      );

      await vi.waitFor(() => {
        expect(
          mockSessionStoreSetters.setPendingPermissions,
        ).toHaveBeenCalledWith("run-123", expect.any(Map));
      });

      const permissions = mockSessionStoreSetters.setPendingPermissions.mock
        .calls[0]?.[1] as Map<
        string,
        { taskRunId: string; options: unknown[] }
      >;
      expect(permissions.get("tool-1")).toEqual(
        expect.objectContaining({
          taskRunId: "run-123",
          options: [
            { optionId: "option_0", name: "cats", kind: "allow_once" },
            { optionId: "option_1", name: "dogs", kind: "allow_once" },
          ],
        }),
      );
      expect(
        mockNotificationService.notifyPermissionRequest,
      ).toHaveBeenCalled();
    });

    it("does NOT seed an optimistic user-message when hydration finds prior history", async () => {
      const service = getSessionService();
      const reopenedSession = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "disconnected",
        isCloud: true,
        events: [],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        reopenedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": reopenedSession,
      });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      // Non-empty history: a prior session/prompt exists.
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue(
        JSON.stringify({
          type: "request",
          timestamp: "2024-01-01T00:00:00Z",
          request: {
            jsonrpc: "2.0",
            id: 1,
            method: "session/prompt",
            params: { prompt: [{ type: "text", text: "hello there" }] },
          },
        }),
      );
      mockTrpcLogs.writeLocalLogs.mutate.mockResolvedValue(undefined);

      const priorPrompt = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          id: 1,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "hello there" }] },
        },
      };
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([priorPrompt]);

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-123",
        undefined,
        "claude",
        undefined,
        "hello there",
      );

      // Wait for hydration to run.
      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-123",
          expect.objectContaining({ events: [priorPrompt] }),
        );
      });
      expect(
        mockSessionStoreSetters.appendOptimisticItem,
      ).not.toHaveBeenCalled();
    });

    it.each([
      { name: "leaf-only response", responseShape: "leaf" },
      { name: "full-chain response", responseShape: "full" },
      { name: "overlapping chain window", responseShape: "overlap" },
    ])(
      "hydrates an in-progress resumed run from a $name",
      async ({ responseShape }) => {
        const service = getSessionService();
        const priorPrompt = {
          type: "acp_message" as const,
          ts: 1700000000,
          message: {
            jsonrpc: "2.0" as const,
            id: 1,
            method: "session/prompt",
            params: { prompt: [{ type: "text", text: "first request" }] },
          },
        };
        const resumePrompt = {
          type: "acp_message" as const,
          ts: 1700000060,
          message: {
            jsonrpc: "2.0" as const,
            id: 2,
            method: "session/prompt",
            params: { prompt: [{ type: "text", text: "continue" }] },
          },
        };
        const resumeCompletion = {
          type: "acp_message" as const,
          ts: 1700000120,
          message: {
            jsonrpc: "2.0" as const,
            method: "_posthog/turn_complete",
            params: { sessionId: "session-1", stopReason: "end_turn" },
          },
        };
        const resumedSession = createMockSession({
          taskRunId: "run-456",
          taskId: "task-123",
          status: "disconnected",
          isCloud: true,
          events: [resumePrompt],
          processedLineCount: 1,
          optimisticItems: [
            {
              id: "optimistic-follow-up",
              type: "user_message",
              content: "continue",
              timestamp: 1700000001,
              pinToTop: false,
            },
          ],
        });
        mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
          resumedSession,
        );
        mockSessionStoreSetters.getSessions.mockReturnValue({
          "run-456": resumedSession,
        });
        const parentEntries = [
          { timestamp: "2024-01-01T00:00:00Z", notification: {} },
          { timestamp: "2024-01-01T00:00:30Z", notification: {} },
        ];
        const leafEntries = [
          { timestamp: "2024-01-01T00:01:00Z", notification: {} },
        ];
        mockAuthenticatedClient.getTaskRunSessionLogsResult
          .mockResolvedValueOnce({ entries: parentEntries, complete: true })
          .mockResolvedValueOnce({
            entries:
              responseShape === "full"
                ? [...parentEntries, ...leafEntries]
                : responseShape === "overlap"
                  ? [parentEntries[1], ...leafEntries]
                  : leafEntries,
            complete: true,
          });
        mockTrpcLogs.readLocalLogs.query.mockResolvedValue(
          JSON.stringify(leafEntries[0]),
        );
        mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");
        mockConvertStoredEntriesToEvents.mockReturnValueOnce([
          priorPrompt,
          resumePrompt,
          resumeCompletion,
        ]);

        service.watchCloudTask(
          "task-123",
          "run-456",
          "https://api.anthropic.com",
          123,
          undefined,
          "https://logs.example.com/run-456",
          undefined,
          "claude",
          undefined,
          "first request",
          undefined,
          "in_progress",
          undefined,
          { resume_from_run_id: "run-123" },
        );

        const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
          .calls[0][1] as { onData: (update: unknown) => void };
        subscribeOptions.onData({
          kind: "snapshot",
          taskId: "task-123",
          runId: "run-456",
          totalEntryCount: 3,
          newEntries: [...parentEntries, ...leafEntries],
          status: "in_progress",
        });
        expect(mockSessionStoreSetters.appendEvents).not.toHaveBeenCalled();

        expect(mockTrpcCloudTask.watch.mutate).toHaveBeenCalledWith({
          taskId: "task-123",
          runId: "run-456",
          apiHost: "https://api.anthropic.com",
          teamId: 123,
          resumeFromEntryCount: undefined,
        });
        await vi.waitFor(() => {
          expect(
            mockAuthenticatedClient.getTaskRunSessionLogsResult,
          ).toHaveBeenCalledWith("task-123", "run-123", { limit: 100000 });
        });
        expect(
          mockAuthenticatedClient.getTaskRunSessionLogsResult,
        ).toHaveBeenCalledWith("task-123", "run-456", { limit: 100000 });
        expect(mockConvertStoredEntriesToEvents).toHaveBeenCalledWith(
          [...parentEntries, ...leafEntries],
          undefined,
          {
            taskRunId: "run-456",
            startEntryIndex: 0,
            firstPositionedEntryIndex: parentEntries.length,
          },
        );
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-456",
          expect.objectContaining({
            events: [priorPrompt, resumePrompt, resumeCompletion],
            processedLineCount: 1,
          }),
        );
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-456",
          expect.objectContaining({
            isPromptPending: false,
            promptStartedAt: null,
            currentPromptId: null,
          }),
        );
        expect(
          mockSessionStoreSetters.clearTailOptimisticItems,
        ).toHaveBeenCalledWith("run-456");
        expect(
          mockSessionStoreSetters.appendOptimisticItem,
        ).not.toHaveBeenCalled();
        expect(mockSessionStoreSetters.appendEvents).not.toHaveBeenCalled();
      },
    );

    it("reconciles repeated prompt occurrences and promptless live tails", async () => {
      const service = getSessionService();
      const ancestorPrompt = {
        type: "acp_message" as const,
        ts: 1700000010,
        message: {
          jsonrpc: "2.0" as const,
          id: 1,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "repeat request" }] },
        },
      };
      const currentLivePrompt = {
        type: "acp_message" as const,
        ts: 1700000040,
        message: ancestorPrompt.message,
      };
      const persistedCurrentPrompt = {
        ...currentLivePrompt,
        ts: 1700000041,
      };
      const persistedAncestorMessage = {
        type: "acp_message" as const,
        ts: 1700000020,
        message: {
          jsonrpc: "2.0" as const,
          method: "session/update",
          params: {
            update: {
              sessionUpdate: "agent_message",
              content: { type: "text", text: "ancestor complete" },
            },
          },
        },
      };
      const currentLiveChunk = {
        type: "acp_message" as const,
        ts: 1700000050,
        message: {
          jsonrpc: "2.0" as const,
          method: "session/update",
          params: {
            sessionId: "current-session",
            update: {
              sessionUpdate: "agent_message_chunk",
              content: { type: "text", text: "current partial" },
            },
          },
        },
      };
      const ancestorCompletion = {
        type: "acp_message" as const,
        ts: 1700000030,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: { stopReason: "end_turn" },
        },
      };
      const currentCompletion = {
        ...ancestorCompletion,
        ts: 1700000060,
      };
      const promptlessLiveOnlyEvent = {
        type: "acp_message" as const,
        ts: 1700000035,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/usage_update",
          params: { used: 42 },
        },
      };
      const resumedSession = createMockSession({
        taskRunId: "run-456",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        events: [
          promptlessLiveOnlyEvent,
          persistedAncestorMessage,
          ancestorCompletion,
          currentLivePrompt,
          currentLiveChunk,
          currentCompletion,
        ],
        processedLineCount: 1,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        resumedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-456": resumedSession,
      });
      const parentEntry = {
        timestamp: "2024-01-01T00:01:00Z",
        notification: {},
      };
      mockAuthenticatedClient.getTaskRunSessionLogsResult
        .mockResolvedValueOnce({ entries: [parentEntry], complete: true })
        .mockResolvedValueOnce({ entries: [parentEntry], complete: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([
        ancestorPrompt,
        persistedAncestorMessage,
        ancestorCompletion,
        persistedCurrentPrompt,
      ]);

      service.watchCloudTask(
        "task-123",
        "run-456",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-456",
        undefined,
        "claude",
        undefined,
        undefined,
        undefined,
        "in_progress",
        undefined,
        { resume_from_run_id: "run-123" },
      );

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-456",
          expect.objectContaining({
            events: [
              ancestorPrompt,
              persistedAncestorMessage,
              ancestorCompletion,
              persistedCurrentPrompt,
              promptlessLiveOnlyEvent,
              currentLiveChunk,
              currentCompletion,
            ],
          }),
        );
      });
    });

    it("preserves a promptless current completion that only matches an ancestor turn", async () => {
      const service = getSessionService();
      const ancestorPrompt = {
        type: "acp_message" as const,
        ts: 1700000010,
        message: {
          jsonrpc: "2.0" as const,
          id: 1,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "ancestor request" }] },
        },
      };
      const currentPrompt = {
        type: "acp_message" as const,
        ts: 1700000040,
        message: {
          jsonrpc: "2.0" as const,
          id: 2,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "current request" }] },
        },
      };
      const ancestorCompletion = {
        type: "acp_message" as const,
        ts: 1700000030,
        message: {
          jsonrpc: "2.0" as const,
          method: "_posthog/turn_complete",
          params: { stopReason: "end_turn" },
        },
      };
      const currentCompletion = {
        ...ancestorCompletion,
        ts: 1700000060,
      };
      const resumedSession = createMockSession({
        taskRunId: "run-456",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        events: [currentCompletion],
        processedLineCount: 1,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        resumedSession,
      );
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-456": resumedSession,
      });
      const parentEntry = {
        timestamp: "2024-01-01T00:01:00Z",
        notification: {},
      };
      mockAuthenticatedClient.getTaskRunSessionLogsResult
        .mockResolvedValueOnce({ entries: [parentEntry], complete: true })
        .mockResolvedValueOnce({ entries: [parentEntry], complete: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");
      mockConvertStoredEntriesToEvents.mockReturnValueOnce([
        ancestorPrompt,
        ancestorCompletion,
        currentPrompt,
      ]);

      service.watchCloudTask(
        "task-123",
        "run-456",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-456",
        undefined,
        "claude",
        undefined,
        undefined,
        undefined,
        "in_progress",
        undefined,
        { resume_from_run_id: "run-123" },
      );

      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-456",
          expect.objectContaining({
            events: [
              ancestorPrompt,
              ancestorCompletion,
              currentPrompt,
              currentCompletion,
            ],
          }),
        );
      });
    });

    it("keeps immediate-resume watcher counts leaf-local while flushing buffered updates", async () => {
      const service = getSessionService();
      const ancestorEvent = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          id: 1,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "first request" }] },
        },
      };
      const leafEvent = {
        type: "acp_message" as const,
        ts: 1700000060,
        message: {
          jsonrpc: "2.0" as const,
          id: 2,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "continue" }] },
        },
      };
      const liveEvent = {
        type: "acp_message" as const,
        ts: 1700000120,
        message: {
          jsonrpc: "2.0" as const,
          method: "session/update",
          params: { update: { sessionUpdate: "agent_message_chunk" } },
        },
      };
      const resumedSession = createMockSession({
        taskRunId: "run-456",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        events: [ancestorEvent],
        cloudTranscriptEntryCount: 3,
        processedLineCount: 0,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        () => resumedSession,
      );
      mockSessionStoreSetters.getSessions.mockImplementation(() => ({
        "run-456": resumedSession,
      }));
      mockSessionStoreSetters.updateSession.mockImplementation(
        (_runId, updates) => Object.assign(resumedSession, updates),
      );
      mockSessionStoreSetters.appendEvents.mockImplementation(
        (_runId, events, processedLineCount) => {
          resumedSession.events.push(...events);
          if (processedLineCount !== undefined) {
            resumedSession.processedLineCount = processedLineCount;
          }
        },
      );

      const ancestorEntries = [
        { timestamp: "2024-01-01T00:00:00Z", notification: {} },
        { timestamp: "2024-01-01T00:00:01Z", notification: {} },
        { timestamp: "2024-01-01T00:00:02Z", notification: {} },
      ];
      const leafEntry = {
        timestamp: "2024-01-01T00:01:00Z",
        notification: {},
      };
      const liveEntry = {
        timestamp: "2024-01-01T00:02:00Z",
        notification: { method: "session/update" },
      };
      let resolveAncestor!: (result: {
        entries: typeof ancestorEntries;
        complete: boolean;
      }) => void;
      mockAuthenticatedClient.getTaskRunSessionLogsResult
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveAncestor = resolve;
            }),
        )
        .mockResolvedValueOnce({
          entries: [...ancestorEntries, leafEntry],
          complete: true,
        });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue(
        JSON.stringify(leafEntry),
      );
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");
      mockConvertStoredEntriesToEvents
        .mockReturnValueOnce([ancestorEvent, leafEvent])
        .mockReturnValueOnce([liveEvent]);

      service.watchCloudTask(
        "task-123",
        "run-456",
        "https://api.anthropic.com",
        123,
        undefined,
        "https://logs.example.com/run-456",
        undefined,
        "claude",
        undefined,
        "first request",
        3,
        "in_progress",
        undefined,
        { resume_from_run_id: "run-123" },
      );

      await vi.waitFor(() => {
        expect(
          mockAuthenticatedClient.getTaskRunSessionLogsResult,
        ).toHaveBeenCalledTimes(2);
      });

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as { onData: (update: unknown) => void };
      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-456",
        totalEntryCount: 5,
        newEntries: [leafEntry, liveEntry],
      });
      expect(mockSessionStoreSetters.appendEvents).not.toHaveBeenCalled();

      resolveAncestor({ entries: ancestorEntries, complete: true });
      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.appendEvents).toHaveBeenCalledWith(
          "run-456",
          [liveEvent],
          2,
        );
      });
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-456",
        expect.objectContaining({
          events: expect.arrayContaining([ancestorEvent, leafEvent]),
          processedLineCount: 1,
        }),
      );
      expect(resumedSession.events).toEqual([
        ancestorEvent,
        leafEvent,
        liveEvent,
      ]);
      expect(resumedSession.processedLineCount).toBe(2);
      expect(mockTrpcCloudTask.watch.mutate).toHaveBeenCalledWith({
        taskId: "task-123",
        runId: "run-456",
        apiHost: "https://api.anthropic.com",
        teamId: 123,
        resumeFromEntryCount: 3,
      });
    });

    it("uses the full A→B transcript count when B resumes into C", async () => {
      const service = getSessionService();
      const aEvent = {
        type: "acp_message" as const,
        ts: 1700000000,
        message: {
          jsonrpc: "2.0" as const,
          id: 1,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "start A" }] },
        },
      };
      const bEvent = {
        type: "acp_message" as const,
        ts: 1700000060,
        message: {
          jsonrpc: "2.0" as const,
          id: 2,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "resume B" }] },
        },
      };
      const cEvent = {
        type: "acp_message" as const,
        ts: 1700000120,
        message: {
          jsonrpc: "2.0" as const,
          id: 3,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "resume C" }] },
        },
      };
      const liveCEvent = {
        type: "acp_message" as const,
        ts: 1700000180,
        message: {
          jsonrpc: "2.0" as const,
          method: "session/update",
          params: { update: { sessionUpdate: "agent_message_chunk" } },
        },
      };
      let activeSession = createMockSession({
        taskRunId: "run-b",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        cloudStatus: "completed",
        cloudBranch: "feature/resume-chain",
        events: [aEvent, bEvent],
        cloudTranscriptEntryCount: 7,
        processedLineCount: 2,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        () => activeSession,
      );
      mockSessionStoreSetters.getSessions.mockImplementation(() => ({
        [activeSession.taskRunId]: activeSession,
      }));
      mockSessionStoreSetters.setSession.mockImplementation((session) => {
        activeSession = session;
      });
      mockSessionStoreSetters.updateSession.mockImplementation(
        (_runId, updates) => Object.assign(activeSession, updates),
      );
      mockSessionStoreSetters.appendEvents.mockImplementation(
        (_runId, events, processedLineCount) => {
          activeSession.events.push(...events);
          if (processedLineCount !== undefined) {
            activeSession.processedLineCount = processedLineCount;
          }
        },
      );

      mockAuthenticatedClient.getTaskRun.mockResolvedValue({
        id: "run-b",
        task: "task-123",
        team: 123,
        branch: "feature/resume-chain",
        runtime_adapter: "claude",
        model: "claude-sonnet-4-20250514",
        reasoning_effort: null,
        environment: "cloud",
        status: "completed",
        log_url: "https://example.com/logs/run-b",
        error_message: null,
        output: {},
        state: { resume_from_run_id: "run-a" },
        created_at: "2026-04-14T00:00:00Z",
        updated_at: "2026-04-14T00:05:00Z",
        completed_at: "2026-04-14T00:05:00Z",
      });
      mockAuthenticatedClient.getTask.mockResolvedValue(createMockTask());
      mockAuthenticatedClient.runTaskInCloud.mockResolvedValue(
        createMockTask({
          latest_run: {
            id: "run-c",
            task: "task-123",
            team: 123,
            branch: "feature/resume-chain",
            runtime_adapter: "claude",
            model: "claude-sonnet-4-20250514",
            reasoning_effort: null,
            environment: "cloud",
            status: "queued",
            log_url: "https://example.com/logs/run-c",
            error_message: null,
            output: {},
            state: { resume_from_run_id: "run-b" },
            created_at: "2026-04-14T00:06:00Z",
            updated_at: "2026-04-14T00:06:00Z",
            completed_at: null,
          },
        }),
      );

      const inheritedEntries = Array.from({ length: 7 }, (_, index) => ({
        timestamp: `2024-01-01T00:00:0${index}Z`,
        notification: {},
      }));
      const cEntry = {
        timestamp: "2024-01-01T00:02:00Z",
        notification: {},
      };
      const liveCEntry = {
        timestamp: "2024-01-01T00:03:00Z",
        notification: { method: "session/update" },
      };
      let resolveInherited!: (result: {
        entries: typeof inheritedEntries;
        complete: boolean;
      }) => void;
      mockAuthenticatedClient.getTaskRunSessionLogsResult
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveInherited = resolve;
            }),
        )
        .mockResolvedValueOnce({
          entries: [...inheritedEntries, cEntry],
          complete: true,
        });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue(
        JSON.stringify(cEntry),
      );
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");
      mockConvertStoredEntriesToEvents
        .mockReturnValueOnce([aEvent, bEvent, cEvent])
        .mockReturnValueOnce([liveCEvent]);

      const result = await service.sendPrompt("task-123", "resume C");
      expect(result.stopReason).toBe("queued");
      expect(activeSession).toEqual(
        expect.objectContaining({
          taskRunId: "run-c",
          cloudTranscriptEntryCount: 7,
          processedLineCount: 0,
        }),
      );
      await vi.waitFor(() => {
        expect(
          mockAuthenticatedClient.getTaskRunSessionLogsResult,
        ).toHaveBeenCalledTimes(2);
      });

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as { onData: (update: unknown) => void };
      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-c",
        totalEntryCount: 9,
        newEntries: [cEntry, liveCEntry],
      });
      expect(mockSessionStoreSetters.appendEvents).not.toHaveBeenCalled();

      resolveInherited({ entries: inheritedEntries, complete: true });
      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.appendEvents).toHaveBeenCalledWith(
          "run-c",
          [liveCEvent],
          2,
        );
      });
      expect(activeSession.events).toEqual([
        aEvent,
        bEvent,
        cEvent,
        liveCEvent,
      ]);
      expect(activeSession.processedLineCount).toBe(2);
      expect(activeSession.cloudTranscriptEntryCount).toBe(9);
      expect(mockTrpcCloudTask.watch.mutate).toHaveBeenCalledWith({
        taskId: "task-123",
        runId: "run-c",
        apiHost: "https://api.anthropic.com",
        teamId: 123,
        resumeFromEntryCount: 7,
      });
    });

    it("switches a cold-reload watcher to leaf-local counts after hydration recovers", async () => {
      const service = getSessionService();
      const resumePrompt = {
        type: "acp_message" as const,
        ts: 1700000060,
        message: {
          jsonrpc: "2.0" as const,
          id: 2,
          method: "session/prompt",
          params: { prompt: [{ type: "text", text: "continue" }] },
        },
      };
      const resumedSession = createMockSession({
        taskRunId: "run-456",
        taskId: "task-123",
        status: "connected",
        isCloud: true,
        events: [],
        processedLineCount: 0,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        () => resumedSession,
      );
      mockSessionStoreSetters.getSessions.mockImplementation(() => ({
        "run-456": resumedSession,
      }));
      mockSessionStoreSetters.updateSession.mockImplementation(
        (_runId, updates) =>
          Object.assign(resumedSession, {
            ...updates,
            ...(updates.events ? { events: [...updates.events] } : {}),
          }),
      );
      mockSessionStoreSetters.appendEvents.mockImplementation(
        (_runId, events, processedLineCount) => {
          resumedSession.events.push(...events);
          if (processedLineCount !== undefined) {
            resumedSession.processedLineCount = processedLineCount;
          }
        },
      );
      const parentEntries = Array.from({ length: 7 }, (_, index) => ({
        timestamp: `2024-01-01T00:00:0${index}Z`,
        notification: {},
      }));
      const leafEntry = {
        timestamp: "2024-01-01T00:01:00Z",
        notification: {},
      };
      const liveEntry = {
        timestamp: "2024-01-01T00:02:00Z",
        notification: { method: "session/update" },
      };
      const liveEvent = {
        type: "acp_message" as const,
        ts: 1700000120,
        message: {
          jsonrpc: "2.0" as const,
          method: "session/update",
          params: { update: { sessionUpdate: "agent_message_chunk" } },
        },
      };
      let resolveAncestor!: (result: {
        entries: typeof parentEntries;
        complete: boolean;
      }) => void;
      mockAuthenticatedClient.getTaskRunSessionLogsResult
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveAncestor = resolve;
            }),
        )
        .mockResolvedValueOnce({
          entries: [...parentEntries, leafEntry],
          complete: true,
        });
      mockConvertStoredEntriesToEvents.mockImplementation((entries) =>
        entries.some(
          (entry) =>
            (entry as { timestamp?: string }).timestamp === liveEntry.timestamp,
        )
          ? [liveEvent]
          : [resumePrompt],
      );

      const watch = (): void => {
        service.watchCloudTask(
          "task-123",
          "run-456",
          "https://api.anthropic.com",
          123,
          undefined,
          "https://logs.example.com/run-456",
          undefined,
          "claude",
          undefined,
          "first request",
          undefined,
          "in_progress",
          undefined,
          { resume_from_run_id: "run-123" },
        );
      };

      watch();
      await vi.waitFor(() => {
        expect(
          mockAuthenticatedClient.getTaskRunSessionLogsResult,
        ).toHaveBeenCalledTimes(2);
      });
      expect(mockTrpcCloudTask.watch.mutate).toHaveBeenCalledWith({
        taskId: "task-123",
        runId: "run-456",
        apiHost: "https://api.anthropic.com",
        teamId: 123,
        resumeFromEntryCount: undefined,
      });
      watch();
      expect(
        mockAuthenticatedClient.getTaskRunSessionLogsResult,
      ).toHaveBeenCalledTimes(2);

      const subscribeOptions = mockTrpcCloudTask.onUpdate.subscribe.mock
        .calls[0][1] as { onData: (update: unknown) => void };
      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-456",
        totalEntryCount: 8,
        newEntries: [...parentEntries, leafEntry],
      });
      expect(mockSessionStoreSetters.appendEvents).not.toHaveBeenCalled();

      resolveAncestor({ entries: parentEntries, complete: false });
      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.appendEvents).toHaveBeenCalledWith(
          "run-456",
          [resumePrompt],
          8,
        );
      });
      expect(resumedSession.processedLineCount).toBe(8);

      let resolveRetryAncestor!: (result: {
        entries: typeof parentEntries;
        complete: boolean;
      }) => void;
      mockAuthenticatedClient.getTaskRunSessionLogsResult
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveRetryAncestor = resolve;
            }),
        )
        .mockResolvedValueOnce({
          entries: [...parentEntries, leafEntry],
          complete: true,
        });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue(
        JSON.stringify(leafEntry),
      );
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");

      watch();
      await vi.waitFor(() => {
        expect(
          mockAuthenticatedClient.getTaskRunSessionLogsResult,
        ).toHaveBeenCalledTimes(4);
      });
      const appendCountBeforeRetryUpdate =
        mockSessionStoreSetters.appendEvents.mock.calls.length;
      subscribeOptions.onData({
        kind: "logs",
        taskId: "task-123",
        runId: "run-456",
        totalEntryCount: 9,
        newEntries: [liveEntry],
      });
      expect(mockSessionStoreSetters.appendEvents).toHaveBeenCalledTimes(
        appendCountBeforeRetryUpdate,
      );

      resolveRetryAncestor({ entries: parentEntries, complete: true });
      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
          "run-456",
          expect.objectContaining({
            events: [resumePrompt],
            processedLineCount: 1,
          }),
        );
      });
      await vi.waitFor(() => {
        expect(mockSessionStoreSetters.appendEvents).toHaveBeenLastCalledWith(
          "run-456",
          [liveEvent],
          2,
        );
      });
      expect(resumedSession.events).toEqual([resumePrompt, liveEvent]);
      expect(resumedSession.processedLineCount).toBe(2);
      expect(resumedSession.cloudTranscriptEntryCount).toBe(9);
    });

    it("ignores stale async starts when the same watcher is replaced", async () => {
      const service = getSessionService();
      let resolveFirstWatchStart!: () => void;
      let resolveSecondWatchStart!: () => void;

      mockTrpcCloudTask.watch.mutate
        .mockImplementationOnce(
          () =>
            new Promise<void>((resolve) => {
              resolveFirstWatchStart = resolve;
            }),
        )
        .mockImplementationOnce(
          () =>
            new Promise<void>((resolve) => {
              resolveSecondWatchStart = resolve;
            }),
        );

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );
      service.stopCloudTaskWatch("task-123");
      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );

      resolveSecondWatchStart();
      await Promise.resolve();
      await Promise.resolve();

      resolveFirstWatchStart();
      await Promise.resolve();
      await Promise.resolve();

      expect(mockTrpcCloudTask.watch.mutate).toHaveBeenCalledTimes(2);
    });

    it("sends a compensating unwatch if teardown wins the race after watch starts", async () => {
      const service = getSessionService();
      let resolveWatchStart!: () => void;
      mockTrpcCloudTask.unwatch.mutate.mockClear();

      mockTrpcCloudTask.watch.mutate.mockImplementationOnce(
        () =>
          new Promise<void>((resolve) => {
            resolveWatchStart = resolve;
          }),
      );

      service.watchCloudTask(
        "task-123",
        "run-123",
        "https://api.anthropic.com",
        123,
      );

      service.stopCloudTaskWatch("task-123");
      expect(mockTrpcCloudTask.unwatch.mutate).not.toHaveBeenCalled();

      resolveWatchStart();
      await Promise.resolve();
      await Promise.resolve();

      expect(mockTrpcCloudTask.unwatch.mutate).toHaveBeenCalledTimes(1);
      expect(mockTrpcCloudTask.unwatch.mutate).toHaveBeenLastCalledWith({
        taskId: "task-123",
        runId: "run-123",
      });
    });

    it("merges model and effort options fetched from preview-config into the cloud session", async () => {
      const service = getSessionService();

      const sessionAfterInit = createMockSession({
        taskRunId: "run-model-123",
        taskId: "task-model-123",
        isCloud: true,
        adapter: "claude",
        configOptions: [
          {
            id: "mode",
            name: "Approval Preset",
            type: "select",
            category: "mode",
            currentValue: "plan",
            options: [],
          },
          {
            id: "model",
            name: "Model",
            type: "select",
            category: "model",
            currentValue: "claude-sonnet-4-6",
            options: [
              {
                value: "claude-sonnet-4-6",
                name: "claude-sonnet-4-6",
              },
            ],
          },
          {
            id: "effort",
            name: "Effort",
            type: "select",
            category: "thought_level",
            currentValue: "high",
            options: [{ value: "high", name: "high" }],
          },
        ],
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-model-123": sessionAfterInit,
      });

      mockTrpcAgent.getPreviewConfigOptions.query.mockResolvedValueOnce([
        {
          id: "mode",
          name: "Approval Preset",
          type: "select",
          category: "mode",
          currentValue: "plan",
          options: [],
        },
        {
          id: "model",
          name: "Model",
          type: "select",
          category: "model",
          currentValue: "claude-opus-4-7",
          options: [
            { value: "claude-opus-4-7", name: "Opus 4.7" },
            { value: "claude-sonnet-4-6", name: "Sonnet 4.6" },
          ],
        },
        {
          id: "effort",
          name: "Effort",
          type: "select",
          category: "thought_level",
          currentValue: "high",
          options: [],
        },
      ]);

      service.watchCloudTask(
        "task-model-123",
        "run-model-123",
        "https://api.example.com",
        7,
        undefined,
        undefined,
        undefined,
        "claude",
        "claude-sonnet-4-6",
      );

      await vi.waitFor(() => {
        expect(
          mockTrpcAgent.getPreviewConfigOptions.query,
        ).toHaveBeenCalledWith({
          apiHost: "https://api.example.com",
          adapter: "claude",
        });
      });

      await vi.waitFor(() => {
        const calls = mockSessionStoreSetters.updateSession.mock.calls as Array<
          [string, { configOptions?: Array<{ id: string }> }]
        >;
        const modelUpdate = calls.find(
          ([runId, patch]) =>
            runId === "run-model-123" &&
            patch.configOptions?.some((o) => o.id === "model"),
        );
        expect(modelUpdate).toBeTruthy();
        const ids = modelUpdate?.[1].configOptions?.map((o) => o.id);
        expect(ids).toEqual(
          expect.arrayContaining(["mode", "model", "effort"]),
        );
        const modelOpt = modelUpdate?.[1].configOptions?.find(
          (o) => o.id === "model",
        ) as
          | {
              currentValue?: string;
              options?: Array<{ name: string; value: string }>;
            }
          | undefined;
        expect(modelOpt?.currentValue).toBe("claude-sonnet-4-6");
        expect(modelOpt?.options).toContainEqual({
          value: "claude-sonnet-4-6",
          name: "Sonnet 4.6",
        });
      });
    });

    it("keeps model-specific max reasoning when generic preview options omit it", async () => {
      const service = getSessionService();
      const session = createMockSession({
        taskRunId: "run-max-123",
        taskId: "task-max-123",
        isCloud: true,
        adapter: "codex",
        configOptions: [
          {
            id: "mode",
            name: "Approval Preset",
            type: "select",
            category: "mode",
            currentValue: "auto",
            options: [],
          },
          {
            id: "model",
            name: "Model",
            type: "select",
            category: "model",
            currentValue: "gpt-5.6-sol",
            options: [{ value: "gpt-5.6-sol", name: "gpt-5.6-sol" }],
          },
          {
            id: "reasoning_effort",
            name: "Reasoning",
            type: "select",
            category: "thought_level",
            currentValue: "max",
            options: [{ value: "max", name: "Max" }],
          },
        ],
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-max-123": session,
      });
      mockTrpcAgent.getPreviewConfigOptions.query.mockResolvedValueOnce([
        {
          id: "model",
          name: "Model",
          type: "select",
          category: "model",
          currentValue: "gpt-5.5",
          options: [
            { value: "gpt-5.5", name: "gpt-5.5" },
            { value: "gpt-5.6-sol", name: "gpt-5.6-sol" },
          ],
        },
        {
          id: "reasoning_effort",
          name: "Reasoning",
          type: "select",
          category: "thought_level",
          currentValue: "high",
          options: [
            { value: "low", name: "Low" },
            { value: "medium", name: "Medium" },
            { value: "high", name: "High" },
            { value: "xhigh", name: "Extra High" },
          ],
        },
      ]);

      service.watchCloudTask(
        "task-max-123",
        "run-max-123",
        "https://api.example.com",
        7,
        undefined,
        undefined,
        "auto",
        "codex",
        "gpt-5.6-sol",
        undefined,
        undefined,
        undefined,
        "max",
      );

      await vi.waitFor(() => {
        const configUpdate = (
          mockSessionStoreSetters.updateSession.mock.calls as Array<
            [string, { configOptions?: SessionConfigOption[] }]
          >
        )
          .filter(([runId]) => runId === "run-max-123")
          .map(([, patch]) => patch.configOptions)
          .find(Boolean);
        const reasoningOption = configUpdate?.find(
          (option) => option.category === "thought_level",
        );
        expect(reasoningOption?.currentValue).toBe("max");
        expect(
          reasoningOption?.type === "select"
            ? reasoningOption.options
            : undefined,
        ).toContainEqual({ value: "max", name: "Max" });
      });
    });

    it("keeps runtime controls omitted from a partial preview response", async () => {
      const service = getSessionService();
      const reasoningOption: SessionConfigOption = {
        id: "reasoning_effort",
        name: "Reasoning",
        type: "select",
        category: "thought_level",
        currentValue: "max",
        options: [{ value: "max", name: "Max" }],
      };
      const session = createMockSession({
        taskRunId: "run-partial-123",
        taskId: "task-partial-123",
        isCloud: true,
        adapter: "codex",
        configOptions: [
          {
            id: "mode",
            name: "Approval Preset",
            type: "select",
            category: "mode",
            currentValue: "auto",
            options: [],
          },
          {
            id: "model",
            name: "Model",
            type: "select",
            category: "model",
            currentValue: "gpt-5.6-sol",
            options: [{ value: "gpt-5.6-sol", name: "gpt-5.6-sol" }],
          },
          reasoningOption,
        ],
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-partial-123": session,
      });
      mockTrpcAgent.getPreviewConfigOptions.query.mockResolvedValueOnce([
        {
          id: "model",
          name: "Model",
          type: "select",
          category: "model",
          currentValue: "gpt-5.5",
          options: [
            { value: "gpt-5.5", name: "gpt-5.5" },
            { value: "gpt-5.6-sol", name: "gpt-5.6-sol" },
          ],
        },
      ]);

      service.watchCloudTask(
        "task-partial-123",
        "run-partial-123",
        "https://api.example.com",
        7,
        undefined,
        undefined,
        "auto",
        "codex",
        "gpt-5.6-sol",
        undefined,
        undefined,
        undefined,
        "max",
      );

      await vi.waitFor(() => {
        const configUpdate = (
          mockSessionStoreSetters.updateSession.mock.calls as Array<
            [string, { configOptions?: SessionConfigOption[] }]
          >
        )
          .filter(([runId]) => runId === "run-partial-123")
          .map(([, patch]) => patch.configOptions)
          .find(Boolean);
        expect(configUpdate).toContainEqual(reasoningOption);
      });
    });

    it("adds a missing selected value to grouped preview options", async () => {
      const service = getSessionService();
      mockGetConfigOptionByCategory.mockImplementation(
        (
          configOptions: Array<{ category?: string }> | undefined,
          category?: string,
        ) => configOptions?.find((option) => option.category === category),
      );
      const session = createMockSession({
        taskRunId: "run-grouped-123",
        taskId: "task-grouped-123",
        isCloud: true,
        adapter: "codex",
        configOptions: [
          {
            id: "mode",
            name: "Approval Preset",
            type: "select",
            category: "mode",
            currentValue: "auto",
            options: [],
          },
          {
            id: "model",
            name: "Model",
            type: "select",
            category: "model",
            currentValue: "gpt-5.6-sol",
            options: [{ value: "gpt-5.6-sol", name: "GPT-5.6 Sol" }],
          },
        ],
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-grouped-123": session,
      });
      mockTrpcAgent.getPreviewConfigOptions.query.mockResolvedValueOnce([
        {
          id: "model",
          name: "Model",
          type: "select",
          category: "model",
          currentValue: "gpt-5.5",
          options: [
            {
              group: "openai",
              name: "OpenAI",
              options: [{ value: "gpt-5.5", name: "GPT-5.5" }],
            },
          ],
        },
      ]);

      service.watchCloudTask(
        "task-grouped-123",
        "run-grouped-123",
        "https://api.example.com",
        7,
        undefined,
        undefined,
        "auto",
        "codex",
        "gpt-5.6-sol",
      );

      await vi.waitFor(() => {
        const configUpdate = (
          mockSessionStoreSetters.updateSession.mock.calls as Array<
            [string, { configOptions?: SessionConfigOption[] }]
          >
        )
          .filter(([runId]) => runId === "run-grouped-123")
          .map(([, patch]) => patch.configOptions)
          .find(Boolean);
        const modelOption = configUpdate?.find(
          (option) => option.category === "model",
        );
        expect(modelOption?.currentValue).toBe("gpt-5.6-sol");
        expect(
          modelOption?.type === "select" &&
            modelOption.options.length > 0 &&
            "group" in modelOption.options[0]
            ? (modelOption.options as SessionConfigSelectGroup[]).flatMap(
                (group) => group.options,
              )
            : undefined,
        ).toContainEqual({ value: "gpt-5.6-sol", name: "GPT-5.6 Sol" });
      });
    });

    it("does not rewrite unchanged cloud preview options", async () => {
      const service = getSessionService();
      const previewOptions = [
        {
          id: "model",
          name: "Model",
          type: "select" as const,
          category: "model" as const,
          currentValue: "gpt-5.6-sol",
          options: [{ value: "gpt-5.6-sol", name: "gpt-5.6-sol" }],
        },
        {
          id: "reasoning_effort",
          name: "Reasoning",
          type: "select" as const,
          category: "thought_level" as const,
          currentValue: "max",
          options: [{ value: "max", name: "Max" }],
        },
      ];
      const session = createMockSession({
        taskRunId: "run-stable-123",
        taskId: "task-stable-123",
        isCloud: true,
        adapter: "codex",
        configOptions: [
          {
            id: "mode",
            name: "Approval Preset",
            type: "select",
            category: "mode",
            currentValue: "auto",
            options: [],
          },
          ...previewOptions,
        ],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-stable-123": session,
      });
      mockTrpcAgent.getPreviewConfigOptions.query.mockResolvedValueOnce([
        {
          id: "mode",
          name: "Approval Preset",
          type: "select",
          category: "mode",
          currentValue: "auto",
          options: [],
        },
        ...previewOptions,
      ]);

      service.watchCloudTask(
        "task-stable-123",
        "run-stable-123",
        "https://api.example.com",
        7,
        undefined,
        undefined,
        "auto",
        "codex",
        "gpt-5.6-sol",
        undefined,
        undefined,
        undefined,
        "max",
      );

      await vi.waitFor(() => {
        expect(
          mockTrpcAgent.getPreviewConfigOptions.query,
        ).toHaveBeenCalledOnce();
      });
      await Promise.resolve();

      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-stable-123",
        expect.objectContaining({ configOptions: expect.any(Array) }),
      );
    });

    it("retries an errored cloud watcher in place", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue({
        ...createMockSession({
          taskId: "task-123",
          taskRunId: "run-123",
          status: "error",
        }),
        isCloud: true,
      });

      await service.retryCloudTaskWatch("task-123");

      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({
          status: "disconnected",
          errorTitle: undefined,
          errorMessage: undefined,
          isPromptPending: false,
        }),
      );
      expect(mockTrpcCloudTask.retry.mutate).toHaveBeenCalledWith({
        taskId: "task-123",
        runId: "run-123",
      });
    });
  });

  describe("retryUnhealthyCloudSessions", () => {
    it("retries every errored cloud session", async () => {
      const service = getSessionService();

      const erroredCloudA: AgentSession = {
        ...createMockSession({
          taskId: "task-a",
          taskRunId: "run-a",
          status: "error",
        }),
        isCloud: true,
      };
      const erroredCloudB: AgentSession = {
        ...createMockSession({
          taskId: "task-b",
          taskRunId: "run-b",
          status: "error",
        }),
        isCloud: true,
      };

      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-a": erroredCloudA,
        "run-b": erroredCloudB,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        (taskId: string) => {
          if (taskId === "task-a") return erroredCloudA;
          if (taskId === "task-b") return erroredCloudB;
          return undefined;
        },
      );

      service.retryUnhealthyCloudSessions();

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.retry.mutate).toHaveBeenCalledTimes(2);
      });
      expect(mockTrpcCloudTask.retry.mutate).toHaveBeenCalledWith({
        taskId: "task-a",
        runId: "run-a",
      });
      expect(mockTrpcCloudTask.retry.mutate).toHaveBeenCalledWith({
        taskId: "task-b",
        runId: "run-b",
      });
    });

    it.each([
      [
        "non-error cloud session (status=connected)",
        {
          ...createMockSession({
            taskId: "task-skip",
            taskRunId: "run-skip",
            status: "connected",
          }),
          isCloud: true,
        } as AgentSession,
      ],
      [
        "non-error cloud session (status=disconnected)",
        {
          ...createMockSession({
            taskId: "task-skip",
            taskRunId: "run-skip",
            status: "disconnected",
          }),
          isCloud: true,
        } as AgentSession,
      ],
      [
        "errored local session (isCloud=false)",
        createMockSession({
          taskId: "task-skip",
          taskRunId: "run-skip",
          status: "error",
        }),
      ],
    ])("skips %s", (_label, session) => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-skip": session,
      });

      service.retryUnhealthyCloudSessions();

      expect(mockTrpcCloudTask.retry.mutate).not.toHaveBeenCalled();
    });

    it("swallows failures so one bad retry doesn't block the rest", async () => {
      const service = getSessionService();
      const errored: AgentSession = {
        ...createMockSession({
          taskId: "task-a",
          taskRunId: "run-a",
          status: "error",
        }),
        isCloud: true,
      };

      mockSessionStoreSetters.getSessions.mockReturnValue({ "run-a": errored });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(errored);
      mockTrpcCloudTask.retry.mutate.mockRejectedValueOnce(
        new Error("network down"),
      );

      expect(() => service.retryUnhealthyCloudSessions()).not.toThrow();
      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.retry.mutate).toHaveBeenCalled();
      });
    });
  });

  describe("reset", () => {
    it("clears connecting tasks", () => {
      const service = getSessionService();
      // Access private map to verify it's cleared
      expect(() => service.reset()).not.toThrow();
    });

    it("unsubscribes from all active subscriptions", async () => {
      const service = getSessionService();

      // Setup: create mocks for subscriptions
      const eventUnsubscribe = vi.fn();
      const permissionUnsubscribe = vi.fn();
      mockTrpcAgent.onSessionEvent.subscribe.mockReturnValue({
        unsubscribe: eventUnsubscribe,
      });
      mockTrpcAgent.onPermissionRequest.subscribe.mockReturnValue({
        unsubscribe: permissionUnsubscribe,
      });

      // Setup: create a task run to trigger subscription creation
      const createTaskRunMock = vi.fn().mockResolvedValue({ id: "run-456" });
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
      mockBuildAuthenticatedClient.mockReturnValue({
        ...mockAuthenticatedClient,
        createTaskRun: createTaskRunMock,
        appendTaskRunLog: vi.fn(),
      });
      mockTrpcAgent.start.mutate.mockResolvedValue({
        channel: "test-channel",
        configOptions: [],
      });

      // Connect to task (this creates subscriptions)
      await service.connectToTask({
        task: createMockTask({ id: "task-456" }),
        repoPath: "/repo",
      });

      // Verify subscriptions were created
      expect(mockTrpcAgent.onSessionEvent.subscribe).toHaveBeenCalled();
      expect(mockTrpcAgent.onPermissionRequest.subscribe).toHaveBeenCalled();

      // Reset the service
      service.reset();

      // Verify unsubscribe was called for both subscriptions
      expect(eventUnsubscribe).toHaveBeenCalled();
      expect(permissionUnsubscribe).toHaveBeenCalled();
    });
  });

  describe("sendPrompt", () => {
    it("throws when offline", async () => {
      mockGetIsOnline.mockReturnValue(false);
      const service = getSessionService();

      await expect(service.sendPrompt("task-123", "Hello")).rejects.toThrow(
        "No internet connection",
      );
    });

    it("throws when no session exists", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);

      await expect(service.sendPrompt("task-123", "Hello")).rejects.toThrow(
        "No active session for task",
      );
    });

    it("throws when session is in error state", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          status: "error",
          errorMessage: "Something went wrong",
        }),
      );

      await expect(service.sendPrompt("task-123", "Hello")).rejects.toThrow(
        "Something went wrong",
      );
    });

    it("throws when session is connecting", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({ status: "connecting" }),
      );

      await expect(service.sendPrompt("task-123", "Hello")).rejects.toThrow(
        "Session is still connecting",
      );
    });

    it("queues message when prompt is already pending", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({ isPromptPending: true }),
      );

      const result = await service.sendPrompt("task-123", "Hello");

      expect(result.stopReason).toBe("queued");
      expect(mockSessionStoreSetters.enqueueMessage).toHaveBeenCalledWith(
        "task-123",
        "Hello",
      );
    });

    it("queues message when compaction is in progress", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({ isCompacting: true }),
      );

      const result = await service.sendPrompt("task-123", "Hello");

      expect(result.stopReason).toBe("queued");
      expect(mockSessionStoreSetters.enqueueMessage).toHaveBeenCalledWith(
        "task-123",
        "Hello",
      );
    });

    it("queues cloud prompt when session.status is not connected (agent not ready)", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          status: "disconnected",
          isPromptPending: false,
        }),
      );

      const prompt: ContentBlock[] = [{ type: "text", text: "wake me up" }];
      const result = await service.sendPrompt("task-123", prompt);

      expect(result.stopReason).toBe("queued");
      expect(mockSessionStoreSetters.enqueueMessage).toHaveBeenCalledWith(
        "task-123",
        "wake me up",
        prompt,
      );
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
    });

    it("sends a native cloud steer immediately", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          status: "connected",
          isPromptPending: true,
          steering: "native",
        }),
      );
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
        result: { stopReason: "steered", steered: true },
      });

      const prompt: ContentBlock[] = [{ type: "text", text: "steer me" }];
      const result = await service.sendPrompt("task-123", prompt, {
        steer: true,
      });

      expect(result.stopReason).toBe("steered");
      expect(mockSessionStoreSetters.enqueueMessage).not.toHaveBeenCalled();
      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "user_message",
          params: { content: "steer me", steer: true },
        }),
      );
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ isPromptPending: false }),
      );
    });

    it("queues a cloud steer when the sandbox lacks the capability", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          status: "connected",
          isPromptPending: true,
          steering: undefined,
        }),
      );

      const prompt: ContentBlock[] = [{ type: "text", text: "steer me" }];
      const result = await service.sendPrompt("task-123", prompt, {
        steer: true,
      });

      expect(result.stopReason).toBe("queued");
      expect(mockSessionStoreSetters.enqueueMessage).toHaveBeenCalledWith(
        "task-123",
        "steer me",
        prompt,
      );
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
    });

    it("kicks an SSE retry when queueing on a disconnected cloud session", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          status: "disconnected",
          isPromptPending: false,
        }),
      );

      const prompt: ContentBlock[] = [{ type: "text", text: "wake me up" }];
      await service.sendPrompt("task-123", prompt);

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.retry.mutate).toHaveBeenCalledWith({
          taskId: "task-123",
          runId: "run-123",
        });
      });
    });

    it("kicks an SSE retry when queueing on an errored cloud session", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          status: "error",
          errorMessage: "Lost connection",
          isPromptPending: false,
        }),
      );

      const prompt: ContentBlock[] = [{ type: "text", text: "wake me up" }];
      await service.sendPrompt("task-123", prompt);

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.retry.mutate).toHaveBeenCalledWith({
          taskId: "task-123",
          runId: "run-123",
        });
      });
    });

    it("does not kick an SSE retry when queueing on a still-connecting cloud session", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          status: "connecting",
          isPromptPending: false,
        }),
      );

      const prompt: ContentBlock[] = [{ type: "text", text: "wake me up" }];
      const result = await service.sendPrompt("task-123", prompt);

      expect(result.stopReason).toBe("queued");
      expect(mockTrpcCloudTask.retry.mutate).not.toHaveBeenCalled();
    });

    it("queues cloud prompt while auth is still restoring", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          status: "connected",
          isPromptPending: false,
        }),
      );
      mockAuth.fetchAuthState.mockResolvedValue({
        status: "restoring",
        bootstrapComplete: false,
        cloudRegion: "us",
        orgProjectsMap: {},
        currentOrgId: null,
        currentProjectId: 123,
        hasCodeAccess: null,
        needsScopeReauth: false,
      });

      const prompt: ContentBlock[] = [{ type: "text", text: "hold this" }];
      const result = await service.sendPrompt("task-123", prompt);

      expect(result.stopReason).toBe("queued");
      expect(mockSessionStoreSetters.enqueueMessage).toHaveBeenCalledWith(
        "task-123",
        "hold this",
        prompt,
      );
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
    });

    it("flushes cloud prompt queued during auth restore after auth is restored", async () => {
      vi.useFakeTimers();
      try {
        const service = getSessionService();
        const prompt: ContentBlock[] = [{ type: "text", text: "hold this" }];
        const queuedMessage = {
          id: "queue-1",
          content: "hold this",
          rawPrompt: prompt,
          queuedAt: 1700000000,
        };
        const session = createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          status: "connected",
          isPromptPending: false,
          messageQueue: [queuedMessage],
        });
        mockSessionStoreSetters.getSessions.mockReturnValue({
          "run-123": session,
        });
        mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
        mockSessionStoreSetters.dequeueMessages.mockReturnValue([
          queuedMessage,
        ]);
        mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
          success: true,
          result: { queued: true },
        });

        service.flushQueuedCloudMessagesAfterAuthRestored();
        await vi.advanceTimersByTimeAsync(0);

        await vi.waitFor(() => {
          expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
            expect.objectContaining({
              taskId: "task-123",
              runId: "run-123",
              method: "user_message",
            }),
          );
        });
        expect(mockSessionStoreSetters.dequeueMessages).toHaveBeenCalledWith(
          "task-123",
          { stopAtEdited: true, max: 1 },
        );
      } finally {
        vi.useRealTimers();
      }
    });

    it("does not drain the cloud queue while auth is still restoring", async () => {
      vi.useFakeTimers();
      try {
        const service = getSessionService();
        const prompt: ContentBlock[] = [{ type: "text", text: "hold this" }];
        const queuedMessage = {
          id: "queue-1",
          content: "hold this",
          rawPrompt: prompt,
          queuedAt: 1700000000,
        };
        const session = createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          status: "connected",
          isPromptPending: false,
          messageQueue: [queuedMessage],
        });
        mockSessionStoreSetters.getSessions.mockReturnValue({
          "run-123": session,
        });
        mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
        mockSessionStoreSetters.dequeueMessages.mockReturnValue([
          queuedMessage,
        ]);
        mockAuth.fetchAuthState.mockResolvedValue({
          status: "restoring",
          bootstrapComplete: false,
          cloudRegion: "us",
          orgProjectsMap: {},
          currentOrgId: null,
          currentProjectId: 123,
          hasCodeAccess: null,
          needsScopeReauth: false,
        });

        service.flushQueuedCloudMessagesAfterAuthRestored();
        await vi.advanceTimersByTimeAsync(10);

        expect(mockSessionStoreSetters.dequeueMessages).not.toHaveBeenCalled();
        expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });

    it("counts queued messages across cloud sessions only", () => {
      const service = getSessionService();
      const queued = (id: string) => ({
        id,
        content: "queued",
        rawPrompt: [{ type: "text", text: "queued" }] as ContentBlock[],
        queuedAt: 1700000000,
      });
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-cloud-a": createMockSession({
          isCloud: true,
          messageQueue: [queued("a1"), queued("a2")],
        }),
        "run-local": createMockSession({
          isCloud: false,
          messageQueue: [queued("l1")],
        }),
        "run-cloud-empty": createMockSession({
          isCloud: true,
          messageQueue: [],
        }),
      });

      expect(service.countQueuedCloudMessages()).toBe(2);
    });

    it("does not pin isPromptPending when queueing during sandbox boot", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "queued",
          status: "connecting",
          isPromptPending: false,
        }),
      );

      const prompt: ContentBlock[] = [{ type: "text", text: "before boot" }];
      const result = await service.sendPrompt("task-123", prompt);

      expect(result.stopReason).toBe("queued");
      expect(mockSessionStoreSetters.enqueueMessage).toHaveBeenCalledWith(
        "task-123",
        "before boot",
        prompt,
      );
      const wroteIsPromptPendingTrue =
        mockSessionStoreSetters.updateSession.mock.calls.some(
          ([, patch]) => patch?.isPromptPending === true,
        );
      expect(wroteIsPromptPendingTrue).toBe(false);
    });

    it("preserves cloud attachment prompts when queueing a follow-up", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          isPromptPending: true,
        }),
      );

      const prompt: ContentBlock[] = [
        { type: "text", text: "read this" },
        {
          type: "resource_link",
          uri: "file:///tmp/test.txt",
          name: "test.txt",
          mimeType: "text/plain",
        },
      ];

      const result = await service.sendPrompt("task-123", prompt);

      expect(result.stopReason).toBe("queued");
      expect(mockSessionStoreSetters.enqueueMessage).toHaveBeenCalledWith(
        "task-123",
        "read this\n\nAttached files: test.txt",
        prompt,
      );
    });

    it("sends prompt via tRPC when session is ready", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession(),
      );
      mockTrpcAgent.prompt.mutate.mockResolvedValue({ stopReason: "end_turn" });

      const result = await service.sendPrompt("task-123", "Hello");

      expect(result.stopReason).toBe("end_turn");
      expect(mockTrpcAgent.prompt.mutate).toHaveBeenCalledWith({
        sessionId: "run-123",
        prompt: [{ type: "text", text: "Hello" }],
      });
    });

    it("uploads attachments before sending cloud follow-ups", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
        }),
      );
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
        result: { queued: true },
      });
      mockTrpcFs.readFileAsBase64.query.mockResolvedValue("aGVsbG8=");
      mockAuthenticatedClient.prepareTaskRunArtifactUploads.mockResolvedValue([
        {
          id: "artifact-1",
          name: "test.txt",
          type: "user_attachment",
          source: "posthog_code",
          size: 5,
          content_type: "text/plain",
          storage_path: "tasks/artifacts/test.txt",
          expires_in: 3600,
          presigned_post: {
            url: "https://uploads.example.com",
            fields: { key: "tasks/artifacts/test.txt" },
          },
        },
      ]);
      mockAuthenticatedClient.finalizeTaskRunArtifactUploads.mockResolvedValue([
        {
          id: "artifact-1",
          name: "test.txt",
          type: "user_attachment",
          source: "posthog_code",
          size: 5,
          content_type: "text/plain",
          storage_path: "tasks/artifacts/test.txt",
          uploaded_at: "2026-04-16T00:00:00Z",
        },
      ]);
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({ ok: true } as Response),
      );

      const prompt: ContentBlock[] = [
        { type: "text", text: "read this" },
        {
          type: "resource_link",
          uri: "file:///tmp/test.txt",
          name: "test.txt",
          mimeType: "text/plain",
        },
      ];

      const result = await service.sendPrompt("task-123", prompt);

      expect(result.stopReason).toBe("queued");
      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledTimes(1);
      expect(mockSessionStoreSetters.appendOptimisticItem).toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({
          type: "user_message",
          content: "read this\n\nAttached files: test.txt",
          pinToTop: false,
        }),
      );

      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
        expect.objectContaining({
          params: {
            content: "read this",
            artifact_ids: ["artifact-1"],
          },
        }),
      );
    });

    it("resolves raw local skill slash commands before sending cloud follow-ups", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
        }),
      );
      mockTrpcSkills.list.query.mockResolvedValue([
        {
          name: "local-test-skill",
          description: "Local user skill",
          source: "user",
          path: "/Users/example/.claude/skills/local-test-skill",
        },
      ]);
      mockTrpcSkills.bundleLocal.query.mockResolvedValue({
        name: "local-test-skill",
        source: "user",
        fileName: "local-test-skill.zip",
        contentType: "application/zip",
        contentBase64: btoa("skill-bundle"),
        contentSha256:
          "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        size: 12,
      });
      mockAuthenticatedClient.prepareTaskRunArtifactUploads.mockResolvedValue([
        {
          id: "skill-prep-1",
          name: "local-test-skill.zip",
          type: "skill_bundle",
          source: "posthog_code_skill",
          size: 12,
          content_type: "application/zip",
          storage_path: "tasks/artifacts/local-test-skill.zip",
          expires_in: 3600,
          presigned_post: {
            url: "https://uploads.example.com",
            fields: { key: "tasks/artifacts/local-test-skill.zip" },
          },
        },
      ]);
      mockAuthenticatedClient.finalizeTaskRunArtifactUploads.mockResolvedValue([
        {
          id: "skill-artifact-1",
          name: "local-test-skill.zip",
          type: "skill_bundle",
          source: "posthog_code_skill",
          size: 12,
          content_type: "application/zip",
          storage_path: "tasks/artifacts/local-test-skill.zip",
          uploaded_at: "2026-04-16T00:00:00Z",
        },
      ]);
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
        result: { queued: true },
      });
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({ ok: true } as Response),
      );

      const result = await service.sendPrompt("task-123", "/local-test-skill");

      expect(result.stopReason).toBe("queued");
      expect(mockTrpcSkills.bundleLocal.query).toHaveBeenCalledWith({
        name: "local-test-skill",
        source: "user",
        path: "/Users/example/.claude/skills/local-test-skill",
      });
      expect(
        mockAuthenticatedClient.prepareTaskRunArtifactUploads,
      ).toHaveBeenCalledWith("task-123", "run-123", [
        expect.objectContaining({
          name: "local-test-skill.zip",
          type: "skill_bundle",
          source: "posthog_code_skill",
          metadata: expect.objectContaining({
            skill_name: "local-test-skill",
            skill_source: "user",
          }),
        }),
      ]);
      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "user_message",
          params: {
            content: "/local-test-skill",
            artifact_ids: ["skill-artifact-1"],
          },
        }),
      );
    });

    it("preserves codex runtime selection when resuming a terminal cloud run", async () => {
      const service = getSessionService();
      mockSettingsState.spokenNotifications = true;
      mockFeatureFlags.isEnabled.mockReturnValue(true);
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "completed",
          cloudBranch: "feature/codex-run",
          adapter: "codex",
          configOptions: [
            {
              id: "model",
              name: "Model",
              type: "select",
              category: "model",
              currentValue: "gpt-5.4",
              options: [],
            },
            {
              id: "effort",
              name: "Effort",
              type: "select",
              category: "thought_level",
              currentValue: "high",
              options: [],
            },
          ],
        }),
      );
      mockGetConfigOptionByCategory.mockImplementation(
        (
          configOptions: Array<{ category?: string }> | undefined,
          category?: string,
        ) => configOptions?.find((opt) => opt.category === category),
      );
      mockAuthenticatedClient.getTaskRun.mockResolvedValue({
        id: "run-123",
        task: "task-123",
        team: 123,
        branch: "feature/codex-run",
        runtime_adapter: "codex",
        model: "gpt-5.4",
        reasoning_effort: "high",
        environment: "cloud",
        status: "completed",
        log_url: "https://example.com/logs/run-123",
        error_message: null,
        output: {},
        state: {},
        created_at: "2026-04-14T00:00:00Z",
        updated_at: "2026-04-14T00:00:00Z",
        completed_at: "2026-04-14T00:05:00Z",
      });
      mockAuthenticatedClient.getTask.mockResolvedValue(createMockTask());
      mockAuthenticatedClient.runTaskInCloud.mockResolvedValue(
        createMockTask({
          latest_run: {
            id: "run-456",
            task: "task-123",
            team: 123,
            branch: "feature/codex-run",
            runtime_adapter: "codex",
            model: "gpt-5.4",
            reasoning_effort: "high",
            environment: "cloud",
            status: "queued",
            log_url: "https://example.com/logs/run-456",
            error_message: null,
            output: {},
            state: {},
            created_at: "2026-04-14T00:06:00Z",
            updated_at: "2026-04-14T00:06:00Z",
            completed_at: null,
          },
        }),
      );

      const result = await service.sendPrompt(
        "task-123",
        "Continue with Codex",
      );

      expect(result.stopReason).toBe("queued");
      expect(mockAuthenticatedClient.runTaskInCloud).toHaveBeenCalledWith(
        "task-123",
        "feature/codex-run",
        expect.objectContaining({
          adapter: "codex",
          model: "gpt-5.4",
          reasoningLevel: "high",
          resumeFromRunId: "run-123",
        }),
      );
    });

    it("shows an optimistic user bubble when resuming a terminal cloud run", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "completed",
          cloudBranch: "feature/cloud-run",
        }),
      );
      mockAuthenticatedClient.getTaskRun.mockResolvedValue({
        id: "run-123",
        task: "task-123",
        team: 123,
        branch: "feature/cloud-run",
        runtime_adapter: "claude",
        model: "claude-sonnet-4-20250514",
        reasoning_effort: null,
        environment: "cloud",
        status: "completed",
        log_url: "https://example.com/logs/run-123",
        error_message: null,
        output: {},
        state: {},
        created_at: "2026-04-14T00:00:00Z",
        updated_at: "2026-04-14T00:00:00Z",
        completed_at: "2026-04-14T00:05:00Z",
      });
      mockAuthenticatedClient.getTask.mockResolvedValue(createMockTask());
      mockTrpcFs.readFileAsBase64.query.mockResolvedValue("aGVsbG8=");
      mockAuthenticatedClient.prepareTaskStagedArtifactUploads.mockResolvedValue(
        [
          {
            id: "artifact-1",
            name: "test.txt",
            type: "user_attachment",
            source: "posthog_code",
            size: 5,
            content_type: "text/plain",
            storage_path: "tasks/artifacts/test.txt",
            expires_in: 3600,
            presigned_post: {
              url: "https://uploads.example.com",
              fields: { key: "tasks/artifacts/test.txt" },
            },
          },
        ],
      );
      mockAuthenticatedClient.finalizeTaskStagedArtifactUploads.mockResolvedValue(
        [
          {
            id: "artifact-1",
            name: "test.txt",
            type: "user_attachment",
            source: "posthog_code",
            size: 5,
            content_type: "text/plain",
            storage_path: "tasks/artifacts/test.txt",
            uploaded_at: "2026-04-16T00:00:00Z",
          },
        ],
      );
      mockAuthenticatedClient.runTaskInCloud.mockResolvedValue(
        createMockTask({
          latest_run: {
            id: "run-456",
            task: "task-123",
            team: 123,
            branch: "feature/cloud-run",
            runtime_adapter: "claude",
            model: "claude-sonnet-4-20250514",
            reasoning_effort: null,
            environment: "cloud",
            status: "queued",
            log_url: "https://example.com/logs/run-456",
            error_message: null,
            output: {},
            state: {},
            created_at: "2026-04-14T00:06:00Z",
            updated_at: "2026-04-14T00:06:00Z",
            completed_at: null,
          },
        }),
      );
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({ ok: true } as Response),
      );

      const prompt: ContentBlock[] = [
        { type: "text", text: "what is this about?" },
        {
          type: "resource_link",
          uri: "file:///tmp/test.txt",
          name: "test.txt",
          mimeType: "text/plain",
        },
      ];

      const result = await service.sendPrompt("task-123", prompt);

      expect(result.stopReason).toBe("queued");
      expect(mockSessionStoreSetters.appendOptimisticItem).toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({
          type: "user_message",
          content: "what is this about?\n\nAttached files: test.txt",
          pinToTop: false,
        }),
      );
      expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
        expect.objectContaining({
          taskRunId: "run-456",
          isPromptPending: true,
        }),
      );
    });

    const mockPreBootFailedSession = (overrides: Partial<AgentSession> = {}) =>
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "failed",
          status: "disconnected",
          ...overrides,
        }),
      );

    it("refuses to resume when the previous run failed before the agent booted", async () => {
      const service = getSessionService();
      mockPreBootFailedSession({
        cloudErrorMessage: "Sandbox could not be provisioned",
      });

      await expect(service.sendPrompt("task-123", "retry?")).rejects.toThrow(
        "Sandbox could not be provisioned",
      );
      expect(mockAuthenticatedClient.runTaskInCloud).not.toHaveBeenCalled();
    });

    it("falls back to a generic message when the failed run has no error", async () => {
      const service = getSessionService();
      mockPreBootFailedSession();

      await expect(service.sendPrompt("task-123", "retry?")).rejects.toThrow(
        /Cloud run couldn't start/,
      );
      expect(mockAuthenticatedClient.runTaskInCloud).not.toHaveBeenCalled();
    });

    it("still resumes when a previously running agent failed mid-execution", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "failed",
          status: "connected",
          cloudBranch: "feature/mid-run",
        }),
      );
      mockAuthenticatedClient.getTaskRun.mockResolvedValue({
        id: "run-123",
        task: "task-123",
        team: 123,
        branch: "feature/mid-run",
        runtime_adapter: "claude",
        model: "claude-sonnet-4-20250514",
        reasoning_effort: null,
        environment: "cloud",
        status: "failed",
        log_url: "https://example.com/logs/run-123",
        error_message: "agent crashed",
        output: {},
        state: {},
        created_at: "2026-04-14T00:00:00Z",
        updated_at: "2026-04-14T00:00:00Z",
        completed_at: "2026-04-14T00:05:00Z",
      });
      mockAuthenticatedClient.getTask.mockResolvedValue(createMockTask());
      mockAuthenticatedClient.runTaskInCloud.mockResolvedValue(
        createMockTask({
          latest_run: {
            id: "run-456",
            task: "task-123",
            team: 123,
            branch: "feature/mid-run",
            runtime_adapter: "claude",
            model: "claude-sonnet-4-20250514",
            reasoning_effort: null,
            environment: "cloud",
            status: "queued",
            log_url: "https://example.com/logs/run-456",
            error_message: null,
            output: {},
            state: {},
            created_at: "2026-04-14T00:06:00Z",
            updated_at: "2026-04-14T00:06:00Z",
            completed_at: null,
          },
        }),
      );

      const result = await service.sendPrompt("task-123", "try again");

      expect(result.stopReason).toBe("queued");
      expect(mockAuthenticatedClient.runTaskInCloud).toHaveBeenCalledTimes(1);
    });

    it("attempts automatic recovery on fatal error", async () => {
      const service = getSessionService();
      const mockSession = createMockSession({
        logUrl: "https://logs.example.com/run-123",
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": { ...mockSession, isPromptPending: false },
      });
      mockTrpcWorkspace.verify.query.mockResolvedValue({ exists: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcAgent.reconnect.mutate.mockResolvedValue({
        sessionId: "run-123",
        channel: "agent-event:run-123",
        configOptions: [],
      });

      await service.connectToTask({
        task: createMockTask({
          latest_run: {
            id: "run-123",
            task: "task-123",
            team: 123,
            environment: "local",
            status: "in_progress",
            log_url: "https://logs.example.com/run-123",
            error_message: null,
            output: null,
            state: {},
            branch: null,
            created_at: "2024-01-01T00:00:00Z",
            updated_at: "2024-01-01T00:00:00Z",
            completed_at: null,
          },
        }),
        repoPath: "/repo",
      });

      mockTrpcAgent.prompt.mutate.mockRejectedValue(
        new Error("Internal error: process exited"),
      );

      await expect(service.sendPrompt("task-123", "Hello")).rejects.toThrow();
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({
          status: "disconnected",
          errorMessage: expect.stringContaining("Reconnecting"),
        }),
      );
    });

    it("does not run session recovery for a transient upstream API timeout", async () => {
      const service = getSessionService();
      const mockSession = createMockSession();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": mockSession,
      });
      mockTrpcAgent.prompt.mutate.mockRejectedValue(
        new Error("Internal error: API Error: the operation timed out"),
      );

      await expect(service.sendPrompt("task-123", "Hello")).rejects.toThrow(
        /provider timed out/,
      );

      // The session stays as-is: no recovery reconnect, no error overlay —
      // only the pending-prompt state is cleared so the user can re-send.
      expect(mockTrpcAgent.reconnect.mutate).not.toHaveBeenCalled();
      expect(mockSessionStoreSetters.updateSession).not.toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ status: "disconnected" }),
      );
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({ isPromptPending: false }),
      );
    });
  });

  describe("local turn_complete + JSON-RPC response ordering", () => {
    it("drains queued messages when turn_complete arrives before the JSON-RPC response (local Codex regression)", async () => {
      const service = getSessionService();

      let session: AgentSession | undefined;
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        () => session,
      );
      mockSessionStoreSetters.getSessions.mockImplementation(() =>
        session ? { "run-123": session } : {},
      );
      mockSessionStoreSetters.updateSession.mockImplementation(
        (_taskRunId, updates) => {
          if (session) session = { ...session, ...updates };
        },
      );
      mockSessionStoreSetters.setSession.mockImplementation((next) => {
        session = next as AgentSession;
      });
      mockSessionStoreSetters.dequeueMessagesAsText.mockReturnValue(
        "follow up",
      );

      mockBuildAuthenticatedClient.mockReturnValue({
        ...mockAuthenticatedClient,
        createTaskRun: vi.fn().mockResolvedValue({ id: "run-123" }),
        appendTaskRunLog: vi.fn(),
      });
      mockTrpcAgent.start.mutate.mockResolvedValue({
        channel: "agent-event:run-123",
        configOptions: [],
      });
      mockTrpcAgent.prompt.mutate.mockResolvedValue({ stopReason: "end_turn" });

      await service.connectToTask({
        task: createMockTask(),
        repoPath: "/repo",
      });

      const onData = mockTrpcAgent.onSessionEvent.subscribe.mock.calls.at(
        -1,
      )?.[1]?.onData as ((payload: unknown) => void) | undefined;
      expect(onData).toBeDefined();

      const queuedMessage = {
        id: "q-1",
        content: "follow up",
        queuedAt: 1700000000,
      };
      session = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: false,
        currentPromptId: 42,
        isPromptPending: true,
        messageQueue: [queuedMessage],
      });

      onData?.({
        type: "acp_message",
        ts: 1700000001,
        message: {
          jsonrpc: "2.0",
          method: "_posthog/turn_complete",
          params: { sessionId: "acp-session", stopReason: "end_turn" },
        },
      });

      expect(session?.currentPromptId).toBe(42);

      onData?.({
        type: "acp_message",
        ts: 1700000002,
        message: {
          jsonrpc: "2.0",
          id: 42,
          result: { stopReason: "end_turn" },
        },
      });

      await vi.waitFor(() => {
        expect(mockTrpcAgent.prompt.mutate).toHaveBeenCalledWith(
          expect.objectContaining({ sessionId: "run-123" }),
        );
      });
    });
  });

  describe("turn-end queue drain gating", () => {
    async function connectWithLiveSession() {
      const service = getSessionService();

      let session: AgentSession | undefined;
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        () => session,
      );
      mockSessionStoreSetters.getSessions.mockImplementation(() =>
        session ? { "run-123": session } : {},
      );
      mockSessionStoreSetters.updateSession.mockImplementation(
        (_taskRunId, updates) => {
          if (session)
            session = { ...session, ...(updates as Partial<AgentSession>) };
        },
      );
      mockSessionStoreSetters.setSession.mockImplementation((next) => {
        session = next as AgentSession;
      });
      mockSessionStoreSetters.clearEditingQueuedMessage.mockImplementation(
        () => {
          if (session) session = { ...session, editingQueuedId: undefined };
        },
      );

      mockBuildAuthenticatedClient.mockReturnValue({
        ...mockAuthenticatedClient,
        createTaskRun: vi.fn().mockResolvedValue({ id: "run-123" }),
        appendTaskRunLog: vi.fn(),
      });
      mockTrpcAgent.start.mutate.mockResolvedValue({
        channel: "agent-event:run-123",
        configOptions: [],
      });

      await service.connectToTask({
        task: createMockTask(),
        repoPath: "/repo",
      });

      const onData = mockTrpcAgent.onSessionEvent.subscribe.mock.calls.at(
        -1,
      )?.[1]?.onData as ((payload: unknown) => void) | undefined;
      expect(onData).toBeDefined();

      return {
        service,
        onData: onData as (payload: unknown) => void,
        setSession: (next: AgentSession) => {
          session = next;
        },
      };
    }

    const promptResponse = (id: number, stopReason: string) => ({
      type: "acp_message" as const,
      ts: 1700000002,
      message: { jsonrpc: "2.0" as const, id, result: { stopReason } },
    });

    it("fires the turn-complete notification instead of draining when the head message is held by an edit", async () => {
      const { onData, setSession } = await connectWithLiveSession();
      vi.useFakeTimers();
      try {
        setSession(
          createMockSession({
            currentPromptId: 42,
            isPromptPending: true,
            messageQueue: [{ id: "q-1", content: "held", queuedAt: 1 }],
            editingQueuedId: "q-1",
          }),
        );

        onData(promptResponse(42, "end_turn"));
        await vi.advanceTimersByTimeAsync(20);

        expect(
          mockNotificationService.notifyPromptComplete,
        ).toHaveBeenCalledWith("Test Task", "end_turn", "task-123", undefined);
        expect(
          mockSessionStoreSetters.dequeueMessagesAsText,
        ).not.toHaveBeenCalled();
        expect(mockTrpcAgent.prompt.mutate).not.toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });

    it("does not drain the queue when the turn was cancelled", async () => {
      const { onData, setSession } = await connectWithLiveSession();
      vi.useFakeTimers();
      try {
        setSession(
          createMockSession({
            currentPromptId: 42,
            isPromptPending: true,
            messageQueue: [{ id: "q-1", content: "queued", queuedAt: 1 }],
          }),
        );

        onData(promptResponse(42, "cancelled"));
        await vi.advanceTimersByTimeAsync(20);

        expect(
          mockSessionStoreSetters.dequeueMessagesAsText,
        ).not.toHaveBeenCalled();
        expect(mockTrpcAgent.prompt.mutate).not.toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });

    it("drains queued messages one turn at a time", async () => {
      const { onData, setSession } = await connectWithLiveSession();
      vi.useFakeTimers();
      try {
        setSession(
          createMockSession({
            currentPromptId: 42,
            isPromptPending: true,
            messageQueue: [
              { id: "q-1", content: "first", queuedAt: 1 },
              { id: "q-2", content: "second", queuedAt: 2 },
            ],
          }),
        );
        mockSessionStoreSetters.dequeueMessagesAsText
          .mockReturnValueOnce("first")
          .mockReturnValueOnce("second");
        mockTrpcAgent.prompt.mutate.mockResolvedValue({
          stopReason: "end_turn",
        });

        onData(promptResponse(42, "end_turn"));
        await vi.advanceTimersByTimeAsync(20);

        expect(mockTrpcAgent.prompt.mutate).toHaveBeenCalledTimes(1);
        expect(
          mockSessionStoreSetters.dequeueMessagesAsText,
        ).toHaveBeenLastCalledWith("task-123", { stopAtEdited: true, max: 1 });

        // The sent message's turn runs and completes: its prompt echo claims a
        // new id, then its response drains the next queued message.
        onData({
          type: "acp_message",
          ts: 1700000003,
          message: {
            jsonrpc: "2.0",
            id: 43,
            method: "session/prompt",
            params: { prompt: [] },
          },
        });
        onData(promptResponse(43, "end_turn"));
        await vi.advanceTimersByTimeAsync(20);

        expect(mockTrpcAgent.prompt.mutate).toHaveBeenCalledTimes(2);
        expect(
          mockSessionStoreSetters.dequeueMessagesAsText,
        ).toHaveBeenCalledTimes(2);
      } finally {
        vi.useRealTimers();
      }
    });

    it("does not start a second prompt when an edit release races the turn-end drain", async () => {
      const { service, onData, setSession } = await connectWithLiveSession();
      vi.useFakeTimers();
      try {
        setSession(
          createMockSession({
            currentPromptId: 42,
            isPromptPending: true,
            messageQueue: [
              { id: "q-1", content: "first", queuedAt: 1 },
              { id: "q-2", content: "second", queuedAt: 2 },
            ],
            editingQueuedId: "q-2",
          }),
        );
        mockSessionStoreSetters.dequeueMessagesAsText
          .mockReturnValueOnce("first")
          .mockReturnValueOnce("second");
        // Keep the first send in flight so the raced timer must observe it.
        mockTrpcAgent.prompt.mutate.mockImplementation(
          () => new Promise(() => {}),
        );

        // The turn ends (the buffered event flush processes it and schedules a
        // drain timer), then the user cancels the edit before that timer fires
        // (scheduling a second drain via the idle flush).
        onData(promptResponse(42, "end_turn"));
        await vi.advanceTimersToNextTimerAsync();
        service.clearEditingQueuedMessage("task-123");
        await vi.advanceTimersByTimeAsync(20);

        expect(mockTrpcAgent.prompt.mutate).toHaveBeenCalledTimes(1);
        expect(
          mockSessionStoreSetters.dequeueMessagesAsText,
        ).toHaveBeenCalledTimes(1);
      } finally {
        vi.useRealTimers();
      }
    });
  });

  describe("steer echo routing", () => {
    async function connectAndCaptureOnData(): Promise<
      (payload: unknown) => void
    > {
      const service = getSessionService();

      let session: AgentSession | undefined;
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        () => session,
      );
      mockSessionStoreSetters.getSessions.mockImplementation(() =>
        session ? { "run-123": session } : {},
      );
      mockSessionStoreSetters.updateSession.mockImplementation(
        (_taskRunId, updates) => {
          if (session) session = { ...session, ...updates };
        },
      );
      mockSessionStoreSetters.setSession.mockImplementation((next) => {
        session = next as AgentSession;
      });

      mockBuildAuthenticatedClient.mockReturnValue({
        ...mockAuthenticatedClient,
        createTaskRun: vi.fn().mockResolvedValue({ id: "run-123" }),
        appendTaskRunLog: vi.fn(),
      });
      mockTrpcAgent.start.mutate.mockResolvedValue({
        channel: "agent-event:run-123",
        configOptions: [],
      });

      await service.connectToTask({
        task: createMockTask(),
        repoPath: "/repo",
      });

      session = createMockSession({
        taskRunId: "run-123",
        taskId: "task-123",
        status: "connected",
        isCloud: false,
        adapter: "claude",
        currentPromptId: 42,
        isPromptPending: true,
      });

      const onData = mockTrpcAgent.onSessionEvent.subscribe.mock.calls.at(
        -1,
      )?.[1]?.onData as ((payload: unknown) => void) | undefined;
      expect(onData).toBeDefined();
      return onData as (payload: unknown) => void;
    }

    it.each([
      {
        name: "appends a steer echo without clearing pending optimistic placeholders",
        steer: true,
      },
      {
        name: "replaces the optimistic placeholder for a normal prompt echo",
        steer: false,
      },
    ])("$name", async ({ steer }) => {
      const onData = await connectAndCaptureOnData();
      mockSessionStoreSetters.appendEvents.mockClear();
      mockSessionStoreSetters.replaceOptimisticWithEvent.mockClear();

      const echo = {
        type: "acp_message",
        ts: 1700000001,
        message: {
          jsonrpc: "2.0",
          id: 101,
          method: "session/prompt",
          params: {
            prompt: [{ type: "text", text: "hello" }],
            ...(steer ? { _meta: { steer: true } } : {}),
          },
        },
      };
      onData(echo);
      // Streamed events are buffered and flushed on a frame timer; let it run.
      await new Promise((resolve) => setTimeout(resolve, 25));

      if (steer) {
        expect(mockSessionStoreSetters.appendEvents).toHaveBeenCalledWith(
          "run-123",
          [echo],
        );
        expect(
          mockSessionStoreSetters.replaceOptimisticWithEvent,
        ).not.toHaveBeenCalled();
      } else {
        expect(
          mockSessionStoreSetters.replaceOptimisticWithEvent,
        ).toHaveBeenCalledWith("run-123", echo);
        expect(mockSessionStoreSetters.appendEvents).not.toHaveBeenCalled();
      }
    });
  });

  describe("steerQueuedMessage", () => {
    const queuedMessage = {
      id: "q-1",
      content: "do the thing",
      queuedAt: 1700000000,
    };

    it("removes the message and resends it as a native steer", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          adapter: "claude",
          isPromptPending: true,
          messageQueue: [
            queuedMessage,
            { id: "q-2", content: "keep me", queuedAt: 1700000001 },
          ],
        }),
      );
      mockTrpcAgent.prompt.mutate.mockResolvedValue({ stopReason: "end_turn" });

      await service.steerQueuedMessage("task-123", "q-1");

      expect(mockSessionStoreSetters.removeQueuedMessage).toHaveBeenCalledWith(
        "task-123",
        "q-1",
      );
      expect(mockTrpcAgent.prompt.mutate).toHaveBeenCalledWith({
        sessionId: "run-123",
        prompt: [{ type: "text", text: "do the thing" }],
        steer: true,
      });
      expect(
        mockSessionStoreSetters.prependQueuedMessages,
      ).not.toHaveBeenCalled();
    });

    it("is a no-op when the message id is not queued", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          adapter: "claude",
          isPromptPending: true,
          messageQueue: [queuedMessage],
        }),
      );

      await service.steerQueuedMessage("task-123", "missing");

      expect(
        mockSessionStoreSetters.removeQueuedMessage,
      ).not.toHaveBeenCalled();
      expect(mockTrpcAgent.prompt.mutate).not.toHaveBeenCalled();
    });

    it("rolls the message back onto the queue when the steer fails", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          adapter: "claude",
          isPromptPending: true,
          messageQueue: [queuedMessage],
        }),
      );
      mockTrpcAgent.prompt.mutate.mockRejectedValue(new Error("steer failed"));

      await expect(
        service.steerQueuedMessage("task-123", "q-1"),
      ).rejects.toThrow("steer failed");

      expect(
        mockSessionStoreSetters.prependQueuedMessages,
      ).toHaveBeenCalledWith("task-123", [queuedMessage]);
    });

    it("is a no-op while compacting and keeps the queued message intact", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          adapter: "claude",
          isPromptPending: true,
          isCompacting: true,
          messageQueue: [queuedMessage],
        }),
      );

      await service.steerQueuedMessage("task-123", "q-1");

      expect(
        mockSessionStoreSetters.removeQueuedMessage,
      ).not.toHaveBeenCalled();
      expect(mockSessionStoreSetters.enqueueMessage).not.toHaveBeenCalled();
      expect(mockTrpcAgent.prompt.mutate).not.toHaveBeenCalled();
    });

    it("resends the original rawPrompt blocks, not the plain-text content", async () => {
      const service = getSessionService();
      const rawPrompt: ContentBlock[] = [{ type: "text", text: "rich blocks" }];
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          adapter: "claude",
          isPromptPending: true,
          messageQueue: [
            { id: "q-rich", content: "plain text", rawPrompt, queuedAt: 1 },
          ],
        }),
      );
      mockTrpcAgent.prompt.mutate.mockResolvedValue({ stopReason: "end_turn" });

      await service.steerQueuedMessage("task-123", "q-rich");

      expect(mockTrpcAgent.prompt.mutate).toHaveBeenCalledWith({
        sessionId: "run-123",
        prompt: [{ type: "text", text: "rich blocks" }],
        steer: true,
      });
    });
  });

  describe("in-place edit hold release", () => {
    const seedEditedIdleSession = (
      overrides: Partial<AgentSession> = {},
    ): AgentSession => {
      const session = createMockSession({
        isCloud: false,
        status: "connected",
        isPromptPending: false,
        messageQueue: [{ id: "q-1", content: "old", queuedAt: 1 }],
        editingQueuedId: "q-1",
        ...overrides,
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": session,
      });
      // Mirror the real store so the flush's readiness check sees the hold gone.
      mockSessionStoreSetters.clearEditingQueuedMessage.mockImplementation(
        () => {
          session.editingQueuedId = undefined;
        },
      );
      return session;
    };

    it("saving an edit while the agent is idle clears the hold and drains the queue", async () => {
      vi.useFakeTimers();
      try {
        const service = getSessionService();
        seedEditedIdleSession();
        mockSessionStoreSetters.dequeueMessagesAsText.mockReturnValue("edited");
        mockTrpcAgent.prompt.mutate.mockResolvedValue({
          stopReason: "end_turn",
        });

        const updated = await service.updateQueuedMessage(
          "task-123",
          "q-1",
          "edited",
        );
        await vi.advanceTimersByTimeAsync(0);

        expect(updated).toBe(true);
        expect(
          mockSessionStoreSetters.updateQueuedMessage,
        ).toHaveBeenCalledWith("task-123", "q-1", { content: "edited" });
        expect(
          mockSessionStoreSetters.clearEditingQueuedMessage,
        ).toHaveBeenCalledWith("task-123");
        expect(
          mockSessionStoreSetters.dequeueMessagesAsText,
        ).toHaveBeenCalledWith("task-123", { stopAtEdited: true, max: 1 });
        expect(mockTrpcAgent.prompt.mutate).toHaveBeenCalledWith(
          expect.objectContaining({ sessionId: "run-123" }),
        );
      } finally {
        vi.useRealTimers();
      }
    });

    it("returns false and keeps the hold when the target is no longer queued", async () => {
      const service = getSessionService();
      seedEditedIdleSession({
        messageQueue: [{ id: "q-other", content: "x", queuedAt: 1 }],
      });

      const updated = await service.updateQueuedMessage(
        "task-123",
        "q-1",
        "edited",
      );

      expect(updated).toBe(false);
      expect(
        mockSessionStoreSetters.updateQueuedMessage,
      ).not.toHaveBeenCalled();
      expect(
        mockSessionStoreSetters.clearEditingQueuedMessage,
      ).not.toHaveBeenCalled();
    });

    it("saving an edit while the agent is still busy does not send immediately", async () => {
      vi.useFakeTimers();
      try {
        const service = getSessionService();
        seedEditedIdleSession({ isPromptPending: true });

        await service.updateQueuedMessage("task-123", "q-1", "edited");
        await vi.advanceTimersByTimeAsync(0);

        expect(
          mockSessionStoreSetters.clearEditingQueuedMessage,
        ).toHaveBeenCalledWith("task-123");
        // Left for the turn-end drain — nothing sent mid-turn.
        expect(
          mockSessionStoreSetters.dequeueMessagesAsText,
        ).not.toHaveBeenCalled();
        expect(mockTrpcAgent.prompt.mutate).not.toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });

    it("cancelling an edit while idle drains the messages the hold was blocking", async () => {
      vi.useFakeTimers();
      try {
        const service = getSessionService();
        seedEditedIdleSession();
        mockSessionStoreSetters.dequeueMessagesAsText.mockReturnValue("q-1");
        mockTrpcAgent.prompt.mutate.mockResolvedValue({
          stopReason: "end_turn",
        });

        service.clearEditingQueuedMessage("task-123");
        await vi.advanceTimersByTimeAsync(0);

        expect(
          mockSessionStoreSetters.dequeueMessagesAsText,
        ).toHaveBeenCalledWith("task-123", { stopAtEdited: true, max: 1 });
        expect(mockTrpcAgent.prompt.mutate).toHaveBeenCalled();
      } finally {
        vi.useRealTimers();
      }
    });

    const seedEditedIdleCloudSession = () => {
      const queuedMessage = {
        id: "q-1",
        content: "old",
        rawPrompt: [{ type: "text" as const, text: "old" }],
        queuedAt: 1,
      };
      const session = createMockSession({
        isCloud: true,
        cloudStatus: "in_progress",
        status: "connected",
        isPromptPending: false,
        messageQueue: [queuedMessage],
        editingQueuedId: "q-1",
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": session,
      });
      mockSessionStoreSetters.clearEditingQueuedMessage.mockImplementation(
        () => {
          session.editingQueuedId = undefined;
        },
      );
      mockSessionStoreSetters.dequeueMessages.mockReturnValue([queuedMessage]);
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
        result: { stopReason: "end_turn" },
      });
      return session;
    };

    it("saving a cloud edit while the run is idle flushes the queue", async () => {
      const service = getSessionService();
      seedEditedIdleCloudSession();

      const updated = await service.updateQueuedMessage(
        "task-123",
        "q-1",
        "edited",
      );

      expect(updated).toBe(true);
      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
          expect.objectContaining({
            taskId: "task-123",
            method: "user_message",
          }),
        );
      });
      expect(mockSessionStoreSetters.dequeueMessages).toHaveBeenCalledWith(
        "task-123",
        { stopAtEdited: true, max: 1 },
      );
    });

    it("cancelling a cloud edit while the run is idle flushes the queue", async () => {
      const service = getSessionService();
      seedEditedIdleCloudSession();

      service.clearEditingQueuedMessage("task-123");

      await vi.waitFor(() => {
        expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
          expect.objectContaining({
            taskId: "task-123",
            method: "user_message",
          }),
        );
      });
    });
  });

  describe("updateQueuedMessage cloud normalization race", () => {
    const cloudSession = (
      overrides: Partial<AgentSession> = {},
    ): AgentSession =>
      createMockSession({
        isCloud: true,
        cloudStatus: "in_progress",
        status: "connected",
        isPromptPending: true,
        messageQueue: [
          {
            id: "q-1",
            content: "old",
            rawPrompt: [{ type: "text", text: "old" }],
            queuedAt: 1,
          },
        ],
        editingQueuedId: "q-1",
        ...overrides,
      });

    it("returns false when the message drains while cloud normalization awaits", async () => {
      const service = getSessionService();
      // Present for the initial membership check, gone for the post-await
      // re-check (a turn completed and drained it during normalization).
      mockSessionStoreSetters.getSessionByTaskId
        .mockReturnValueOnce(cloudSession())
        .mockReturnValue(
          cloudSession({ messageQueue: [], editingQueuedId: undefined }),
        );

      const updated = await service.updateQueuedMessage(
        "task-123",
        "q-1",
        "edited",
      );

      // No-op store write must not be reported as a save, so the caller falls
      // back to sending the edit as a fresh message instead of losing it.
      expect(updated).toBe(false);
      expect(
        mockSessionStoreSetters.updateQueuedMessage,
      ).not.toHaveBeenCalled();
      expect(
        mockSessionStoreSetters.clearEditingQueuedMessage,
      ).not.toHaveBeenCalled();
    });

    it("updates in place when the message is still queued after normalization", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        cloudSession(),
      );

      const updated = await service.updateQueuedMessage(
        "task-123",
        "q-1",
        "edited",
      );

      expect(updated).toBe(true);
      expect(mockSessionStoreSetters.updateQueuedMessage).toHaveBeenCalledWith(
        "task-123",
        "q-1",
        expect.objectContaining({ content: expect.any(String) }),
      );
    });
  });

  describe("cancelPrompt", () => {
    it("returns false if no session exists", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);

      const result = await service.cancelPrompt("task-123");

      expect(result).toBe(false);
    });

    it("calls cancelPrompt mutation", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession(),
      );
      mockTrpcAgent.cancelPrompt.mutate.mockResolvedValue(true);

      const result = await service.cancelPrompt("task-123");

      expect(result).toBe(true);
      expect(mockTrpcAgent.cancelPrompt.mutate).toHaveBeenCalledWith({
        sessionId: "run-123",
      });
    });

    it("returns false on error", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession(),
      );
      mockTrpcAgent.cancelPrompt.mutate.mockRejectedValue(new Error("Failed"));

      const result = await service.cancelPrompt("task-123");

      expect(result).toBe(false);
    });
  });

  // Surfaces a cloud question through the live watcher update path so the
  // service tracks its cloud requestId, mirroring how real question cards
  // arrive. Returns the session (with the surfaced permission attached) and
  // the update feeder for replay scenarios.
  const surfaceCloudQuestion = (
    service: ReturnType<typeof getSessionService>,
  ) => {
    const session = createMockSession({
      isCloud: true,
      cloudStatus: "in_progress",
      events: [
        {
          type: "acp_message",
          ts: 1700000000,
          message: {
            jsonrpc: "2.0",
            method: "session/update",
            params: { update: { sessionUpdate: "tool_call" } },
          },
        } as AcpMessage,
      ],
      processedLineCount: 3,
    });
    mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(session);
    mockSessionStoreSetters.getSessions.mockReturnValue({ "run-123": session });

    service.watchCloudTask(
      "task-123",
      "run-123",
      "https://api.example.com",
      123,
      undefined,
      "https://logs.example.com/run-123",
      undefined,
      "claude",
    );

    const onData = mockTrpcCloudTask.onUpdate.subscribe.mock.calls[0]?.[1]
      ?.onData as (update: unknown) => void;
    const requestUpdate = {
      kind: "permission_request",
      taskId: "task-123",
      runId: "run-123",
      requestId: "request-1",
      toolCall: {
        toolCallId: "tool-1",
        title: "Which license should I use?",
        kind: "other",
        _meta: {
          codeToolKind: "question",
          questions: [{ question: "Which license should I use?" }],
        },
      },
      options: [{ optionId: "option_0", name: "MIT", kind: "allow_once" }],
    };
    onData(requestUpdate);

    const surfaced =
      mockSessionStoreSetters.setPendingPermissions.mock.calls.at(
        -1,
      )?.[1] as AgentSession["pendingPermissions"];
    session.pendingPermissions = surfaced;
    return { session, onData, requestUpdate };
  };

  describe("respondToPermission", () => {
    it("does nothing if no session exists", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);

      await service.respondToPermission("task-123", "tool-1", "allow");

      expect(mockTrpcAgent.respondToPermission.mutate).not.toHaveBeenCalled();
    });

    it("removes permission from UI and sends response", async () => {
      const service = getSessionService();
      const permissions = new Map([["tool-1", { receivedAt: Date.now() }]]);
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          pendingPermissions: permissions as AgentSession["pendingPermissions"],
        }),
      );

      await service.respondToPermission("task-123", "tool-1", "allow");

      expect(mockSessionStoreSetters.setPendingPermissions).toHaveBeenCalled();
      expect(mockTrpcAgent.respondToPermission.mutate).toHaveBeenCalledWith({
        taskRunId: "run-123",
        toolCallId: "tool-1",
        optionId: "allow",
        customInput: undefined,
        answers: undefined,
      });
    });

    const mockTerminalCloudRun = () => {
      mockAuthenticatedClient.getTaskRun.mockResolvedValue({
        id: "run-123",
        task: "task-123",
        team: 123,
        branch: "feature/cloud-run",
        environment: "cloud",
        status: "completed",
        log_url: "https://example.com/logs/run-123",
        error_message: null,
        output: {},
        state: {},
        created_at: "2026-04-14T00:00:00Z",
        updated_at: "2026-04-14T00:00:00Z",
        completed_at: "2026-04-14T00:05:00Z",
      });
      mockAuthenticatedClient.runTaskInCloud.mockResolvedValue(
        createMockTask({
          latest_run: {
            id: "run-456",
            task: "task-123",
            team: 123,
            branch: "feature/cloud-run",
            environment: "cloud",
            status: "queued",
            log_url: "https://example.com/logs/run-456",
            error_message: null,
            output: {},
            state: {},
            created_at: "2026-04-14T00:06:00Z",
            updated_at: "2026-04-14T00:06:00Z",
            completed_at: null,
          } as Task["latest_run"],
        }),
      );
    };

    const selectedAnswerPrompt = "MIT";

    it("resumes a terminal cloud run with the selected answer as the prompt", async () => {
      const service = getSessionService();
      const permissions = new Map([
        [
          "tool-1",
          {
            taskRunId: "run-123",
            receivedAt: Date.now(),
            toolCall: {
              toolCallId: "tool-1",
              _meta: {
                codeToolKind: "question",
                questions: [{ question: "Which license should I use?" }],
              },
            },
            options: [
              { optionId: "option_0", name: "MIT", kind: "allow_once" },
            ],
          },
        ],
      ]);
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "completed",
          cloudBranch: "feature/cloud-run",
          pendingPermissions: permissions as AgentSession["pendingPermissions"],
        }),
      );
      mockTerminalCloudRun();

      await service.respondToPermission(
        "task-123",
        "tool-1",
        "option_0",
        undefined,
        {
          "Which license should I use?": "MIT",
        },
      );

      // The dead run's permission promise can't be resolved — no command is proxied.
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      expect(mockTrpcAgent.respondToPermission.mutate).not.toHaveBeenCalled();
      expect(mockAuthenticatedClient.runTaskInCloud).toHaveBeenCalledWith(
        "task-123",
        "feature/cloud-run",
        expect.objectContaining({
          resumeFromRunId: "run-123",
          pendingUserMessage: selectedAnswerPrompt,
        }),
      );
    });

    it("refreshes stale cloud run status before answering a terminal question", async () => {
      const service = getSessionService();
      const permissions = new Map([
        [
          "tool-1",
          {
            taskRunId: "run-123",
            receivedAt: Date.now(),
            toolCall: {
              toolCallId: "tool-1",
              _meta: {
                codeToolKind: "question",
                questions: [{ question: "Which license should I use?" }],
              },
            },
            options: [
              { optionId: "option_0", name: "MIT", kind: "allow_once" },
            ],
          },
        ],
      ]);
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          cloudBranch: "feature/cloud-run",
          pendingPermissions: permissions as AgentSession["pendingPermissions"],
        }),
      );
      mockTerminalCloudRun();

      await service.respondToPermission(
        "task-123",
        "tool-1",
        "option_0",
        undefined,
        {
          "Which license should I use?": "MIT",
        },
      );

      expect(mockAuthenticatedClient.getTaskRun).toHaveBeenCalledWith(
        "task-123",
        "run-123",
      );
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      expect(mockTrpcAgent.respondToPermission.mutate).not.toHaveBeenCalled();
      expect(mockAuthenticatedClient.runTaskInCloud).toHaveBeenCalledWith(
        "task-123",
        "feature/cloud-run",
        expect.objectContaining({
          resumeFromRunId: "run-123",
          pendingUserMessage: selectedAnswerPrompt,
        }),
      );
    });

    it("drops a plain approval on a terminal cloud run instead of resuming", async () => {
      const service = getSessionService();
      const permissions = new Map([
        [
          "tool-1",
          {
            taskRunId: "run-123",
            receivedAt: Date.now(),
            toolCall: { toolCallId: "tool-1", kind: "execute" },
            options: [{ optionId: "allow", name: "Allow", kind: "allow_once" }],
          },
        ],
      ]);
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "completed",
          pendingPermissions: permissions as AgentSession["pendingPermissions"],
        }),
      );
      mockTerminalCloudRun();

      await service.respondToPermission("task-123", "tool-1", "allow");

      expect(mockSessionStoreSetters.setPendingPermissions).toHaveBeenCalled();
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      expect(mockTrpcAgent.respondToPermission.mutate).not.toHaveBeenCalled();
      expect(mockAuthenticatedClient.runTaskInCloud).not.toHaveBeenCalled();
    });

    it("persists a durable resolved marker when answering a question on a terminal cloud run", async () => {
      const service = getSessionService();
      surfaceCloudQuestion(service);
      mockTerminalCloudRun();

      await service.respondToPermission(
        "task-123",
        "tool-1",
        "option_0",
        undefined,
        { "Which license should I use?": "MIT" },
      );

      // The answer resumed the run as a prompt; without a resolved marker the
      // request would be re-derived as pending from the log forever.
      expect(mockAuthenticatedClient.runTaskInCloud).toHaveBeenCalled();
      expect(mockAuthenticatedClient.appendTaskRunLog).toHaveBeenCalledWith(
        "task-123",
        "run-123",
        [
          expect.objectContaining({
            type: "notification",
            notification: expect.objectContaining({
              method: "_posthog/permission_resolved",
              params: {
                requestId: "request-1",
                toolCallId: "tool-1",
                optionId: "option_0",
              },
            }),
          }),
        ],
      );
    });

    it("does not re-surface a question the user already answered when the stream re-delivers it", async () => {
      const service = getSessionService();
      const { session, onData, requestUpdate } = surfaceCloudQuestion(service);
      mockTerminalCloudRun();

      await service.respondToPermission(
        "task-123",
        "tool-1",
        "option_0",
        undefined,
        { "Which license should I use?": "MIT" },
      );

      session.pendingPermissions = new Map();
      mockSessionStoreSetters.setPendingPermissions.mockClear();

      // The durable stream re-sends the tail on reconnect/replay.
      onData(requestUpdate);

      expect(
        mockSessionStoreSetters.setPendingPermissions,
      ).not.toHaveBeenCalled();
    });
  });

  describe("cancelPermission", () => {
    it("does nothing if no session exists", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);

      await service.cancelPermission("task-123", "tool-1");

      expect(mockTrpcAgent.cancelPermission.mutate).not.toHaveBeenCalled();
    });

    it("persists a dismissal marker when cancelling a question on a terminal cloud run", async () => {
      const service = getSessionService();
      const { session } = surfaceCloudQuestion(service);
      session.cloudStatus = "completed";

      await service.cancelPermission("task-123", "tool-1");

      // The dead run can't receive a permission_response; record the
      // dismissal so the request is not re-derived as pending from the log.
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      expect(mockAuthenticatedClient.appendTaskRunLog).toHaveBeenCalledWith(
        "task-123",
        "run-123",
        [
          expect.objectContaining({
            type: "notification",
            notification: expect.objectContaining({
              method: "_posthog/permission_resolved",
              params: {
                requestId: "request-1",
                toolCallId: "tool-1",
                optionId: "cancelled",
              },
            }),
          }),
        ],
      );
    });

    it("removes permission from UI and cancels", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession(),
      );

      await service.cancelPermission("task-123", "tool-1");

      expect(mockSessionStoreSetters.setPendingPermissions).toHaveBeenCalled();
      expect(mockTrpcAgent.cancelPermission.mutate).toHaveBeenCalledWith({
        taskRunId: "run-123",
        toolCallId: "tool-1",
      });
    });

    it("resolves locally without proxying a command on a terminal cloud run", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({ isCloud: true, cloudStatus: "completed" }),
      );

      await service.cancelPermission("task-123", "tool-1");

      expect(mockSessionStoreSetters.setPendingPermissions).toHaveBeenCalled();
      expect(mockTrpcCloudTask.sendCommand.mutate).not.toHaveBeenCalled();
      expect(mockTrpcAgent.cancelPermission.mutate).not.toHaveBeenCalled();
    });
  });

  describe("setSessionConfigOption", () => {
    it("does nothing if no session exists", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);

      await service.setSessionConfigOption(
        "task-123",
        "model",
        "claude-3-sonnet",
      );

      expect(mockTrpcAgent.setConfigOption.mutate).not.toHaveBeenCalled();
    });

    it("does nothing if config option not found", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          configOptions: [
            {
              id: "mode",
              name: "Mode",
              type: "select",
              category: "mode",
              currentValue: "default",
              options: [],
            },
          ],
        }),
      );

      await service.setSessionConfigOption(
        "task-123",
        "unknown-option",
        "value",
      );

      expect(mockTrpcAgent.setConfigOption.mutate).not.toHaveBeenCalled();
    });

    it("optimistically updates and calls API", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          configOptions: [
            {
              id: "model",
              name: "Model",
              type: "select",
              category: "model",
              currentValue: "claude-3-opus",
              options: [],
            },
          ],
        }),
      );

      await service.setSessionConfigOption(
        "task-123",
        "model",
        "claude-3-sonnet",
      );

      // Optimistic update
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        {
          configOptions: [
            {
              id: "model",
              name: "Model",
              type: "select",
              category: "model",
              currentValue: "claude-3-sonnet",
              options: [],
            },
          ],
        },
      );
      expect(
        mockSessionConfigStore.setPersistedConfigOptions,
      ).toHaveBeenCalledWith("run-123", [
        expect.objectContaining({
          id: "model",
          currentValue: "claude-3-sonnet",
        }),
      ]);
      expect(mockTrpcAgent.setConfigOption.mutate).toHaveBeenCalledWith({
        sessionId: "run-123",
        configId: "model",
        value: "claude-3-sonnet",
      });
    });

    it("rolls back on API failure", async () => {
      const service = getSessionService();
      let currentSession = createMockSession({
        configOptions: [
          {
            id: "mode",
            name: "Mode",
            type: "select",
            category: "mode",
            currentValue: "default",
            options: [],
          },
        ],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        () => currentSession,
      );
      mockSessionStoreSetters.updateSession.mockImplementation(
        (_taskRunId, updates) => {
          currentSession = { ...currentSession, ...updates };
        },
      );
      mockTrpcAgent.setConfigOption.mutate.mockRejectedValue(
        new Error("Failed"),
      );

      await service.setSessionConfigOption("task-123", "mode", "acceptEdits");

      expect(currentSession.configOptions).toEqual([
        expect.objectContaining({
          id: "mode",
          currentValue: "default",
        }),
      ]);
      expect(
        mockSessionConfigStore.setPersistedConfigOptions,
      ).toHaveBeenLastCalledWith("run-123", [
        expect.objectContaining({
          id: "mode",
          currentValue: "default",
        }),
      ]);
    });

    it("preserves a newer successful config change during rollback", async () => {
      const service = getSessionService();
      let currentSession = createMockSession({
        configOptions: [
          {
            id: "mode",
            name: "Mode",
            type: "select",
            category: "mode",
            currentValue: "default",
            options: [],
          },
          {
            id: "model",
            name: "Model",
            type: "select",
            category: "model",
            currentValue: "claude-3-opus",
            options: [],
          },
        ],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockImplementation(
        () => currentSession,
      );
      mockSessionStoreSetters.updateSession.mockImplementation(
        (_taskRunId, updates) => {
          currentSession = { ...currentSession, ...updates };
        },
      );

      let rejectModeChange: (error: Error) => void = () => undefined;
      const pendingModeChange = new Promise<never>((_resolve, reject) => {
        rejectModeChange = reject;
      });
      mockTrpcAgent.setConfigOption.mutate.mockImplementation(({ configId }) =>
        configId === "mode" ? pendingModeChange : Promise.resolve({}),
      );

      const modeChange = service.setSessionConfigOption(
        "task-123",
        "mode",
        "acceptEdits",
      );
      await service.setSessionConfigOption(
        "task-123",
        "model",
        "claude-3-sonnet",
      );
      rejectModeChange(new Error("Mode change failed"));
      await modeChange;

      expect(currentSession.configOptions).toEqual([
        expect.objectContaining({
          id: "mode",
          currentValue: "default",
        }),
        expect.objectContaining({
          id: "model",
          currentValue: "claude-3-sonnet",
        }),
      ]);
      expect(
        mockSessionConfigStore.setPersistedConfigOptions,
      ).toHaveBeenLastCalledWith("run-123", [
        expect.objectContaining({
          id: "mode",
          currentValue: "default",
        }),
        expect.objectContaining({
          id: "model",
          currentValue: "claude-3-sonnet",
        }),
      ]);
    });

    it("skips backend call when local session is idle-killed so reconnect restore handles it", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          status: "error",
          idleKilled: true,
          configOptions: [
            {
              id: "mode",
              name: "Mode",
              type: "select",
              category: "mode",
              currentValue: "default",
              options: [],
            },
          ],
        }),
      );

      await service.setSessionConfigOption("task-123", "mode", "acceptEdits");

      expect(mockTrpcAgent.setConfigOption.mutate).not.toHaveBeenCalled();
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledTimes(1);
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        {
          configOptions: [
            {
              id: "mode",
              name: "Mode",
              type: "select",
              category: "mode",
              currentValue: "acceptEdits",
              options: [],
            },
          ],
        },
      );
      expect(
        mockSessionConfigStore.setPersistedConfigOptions,
      ).toHaveBeenCalledWith("run-123", [
        expect.objectContaining({
          id: "mode",
          currentValue: "acceptEdits",
        }),
      ]);
    });

    it("skips backend call when local session is reconnecting (disconnected status)", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          status: "disconnected",
          configOptions: [
            {
              id: "mode",
              name: "Mode",
              type: "select",
              category: "mode",
              currentValue: "default",
              options: [],
            },
          ],
        }),
      );

      await service.setSessionConfigOption("task-123", "mode", "acceptEdits");

      expect(mockTrpcAgent.setConfigOption.mutate).not.toHaveBeenCalled();
    });

    it("routes cloud sessions through sendCommand with set_config_option", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession({
          isCloud: true,
          cloudStatus: "in_progress",
          configOptions: [
            {
              id: "model",
              name: "Model",
              type: "select",
              category: "model",
              currentValue: "claude-opus-4-7",
              options: [],
            },
          ],
        }),
      );
      mockTrpcCloudTask.sendCommand.mutate.mockResolvedValue({
        success: true,
      });

      await service.setSessionConfigOption(
        "task-123",
        "model",
        "claude-sonnet-4-6",
      );

      expect(mockTrpcAgent.setConfigOption.mutate).not.toHaveBeenCalled();
      expect(mockTrpcCloudTask.sendCommand.mutate).toHaveBeenCalledWith(
        expect.objectContaining({
          method: "set_config_option",
          params: { configId: "model", value: "claude-sonnet-4-6" },
        }),
      );
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        {
          configOptions: [
            {
              id: "model",
              name: "Model",
              type: "select",
              category: "model",
              currentValue: "claude-sonnet-4-6",
              options: [],
            },
          ],
        },
      );
    });
  });

  describe("clearSessionError", () => {
    it("cancels agent and reconnects in place (no teardown)", async () => {
      const service = getSessionService();
      const mockSession = createMockSession({
        status: "error",
        logUrl: "https://logs.example.com/run-123",
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockTrpcAgent.reconnect.mutate.mockResolvedValue({
        sessionId: "run-123",
        channel: "agent-event:run-123",
        configOptions: [],
      });
      mockTrpcAgent.onSessionEvent.subscribe.mockReturnValue({
        unsubscribe: vi.fn(),
      });
      mockTrpcAgent.onPermissionRequest.subscribe.mockReturnValue({
        unsubscribe: vi.fn(),
      });
      mockTrpcWorkspace.verify.query.mockResolvedValue({ exists: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");

      await service.clearSessionError("task-123", "/repo");

      // Should cancel the backend agent
      expect(mockTrpcAgent.cancel.mutate).toHaveBeenCalledWith({
        sessionId: "run-123",
      });
      // Should NOT remove session from store (avoids connect effect loop)
      expect(mockSessionStoreSetters.removeSession).not.toHaveBeenCalled();
      // Should attempt reconnect in place
      expect(mockTrpcAgent.reconnect.mutate).toHaveBeenCalled();
    });

    it("does not restore persisted options unsupported by the resumed session", async () => {
      const service = getSessionService();
      const modelOption: SessionConfigOption = {
        id: "model",
        name: "Model",
        type: "select",
        category: "model",
        currentValue: "@cf/zai-org/glm-5.2",
        options: [{ value: "@cf/zai-org/glm-5.2", name: "GLM 5.2" }],
      };
      const effortOption: SessionConfigOption = {
        id: "effort",
        name: "Effort",
        type: "select",
        category: "thought_level",
        currentValue: "medium",
        options: [{ value: "medium", name: "Medium" }],
      };
      const mockSession = createMockSession({
        status: "error",
        logUrl: "https://logs.example.com/run-123",
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockSessionConfigStore.getPersistedConfigOptions.mockReturnValue([
        modelOption,
        effortOption,
      ]);
      mockTrpcAgent.reconnect.mutate.mockResolvedValue({
        sessionId: "run-123",
        channel: "agent-event:run-123",
        configOptions: [modelOption],
      });
      mockTrpcWorkspace.verify.query.mockResolvedValue({ exists: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");

      await service.clearSessionError("task-123", "/repo");

      expect(mockTrpcAgent.setConfigOption.mutate).toHaveBeenCalledTimes(1);
      expect(mockTrpcAgent.setConfigOption.mutate).toHaveBeenCalledWith({
        sessionId: "run-123",
        configId: "model",
        value: "@cf/zai-org/glm-5.2",
      });
      expect(
        mockSessionConfigStore.setPersistedConfigOptions,
      ).toHaveBeenCalledWith("run-123", [modelOption]);
    });

    it("drops a persisted value the resumed option no longer offers", async () => {
      const service = getSessionService();
      // Same option id, but the resumed model only offers high/max — the
      // persisted "medium" is stale and must not be restored or displayed.
      const staleEffort: SessionConfigOption = {
        id: "effort",
        name: "Effort",
        type: "select",
        category: "thought_level",
        currentValue: "medium",
        options: [{ value: "medium", name: "Medium" }],
      };
      const liveEffort: SessionConfigOption = {
        id: "effort",
        name: "Effort",
        type: "select",
        category: "thought_level",
        currentValue: "high",
        options: [
          { value: "high", name: "High" },
          { value: "max", name: "Max" },
        ],
      };
      const mockSession = createMockSession({
        status: "error",
        logUrl: "https://logs.example.com/run-123",
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockSessionConfigStore.getPersistedConfigOptions.mockReturnValue([
        staleEffort,
      ]);
      mockTrpcAgent.reconnect.mutate.mockResolvedValue({
        sessionId: "run-123",
        channel: "agent-event:run-123",
        configOptions: [liveEffort],
      });
      mockTrpcWorkspace.verify.query.mockResolvedValue({ exists: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");

      await service.clearSessionError("task-123", "/repo");

      expect(mockTrpcAgent.setConfigOption.mutate).not.toHaveBeenCalled();
      // Stored config keeps the live value, never the rejected "medium".
      expect(
        mockSessionConfigStore.setPersistedConfigOptions,
      ).toHaveBeenCalledWith("run-123", [liveEffort]);
    });

    it("restores nothing when the resumed session reports no options", async () => {
      const service = getSessionService();
      const effortOption: SessionConfigOption = {
        id: "effort",
        name: "Effort",
        type: "select",
        category: "thought_level",
        currentValue: "medium",
        options: [{ value: "medium", name: "Medium" }],
      };
      const mockSession = createMockSession({
        status: "error",
        logUrl: "https://logs.example.com/run-123",
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockSessionConfigStore.getPersistedConfigOptions.mockReturnValue([
        effortOption,
      ]);
      // Reconnect omits configOptions (e.g. after compaction): support can't
      // be confirmed, so persisted options must not be pushed to the server.
      mockTrpcAgent.reconnect.mutate.mockResolvedValue({
        sessionId: "run-123",
        channel: "agent-event:run-123",
      });
      mockTrpcWorkspace.verify.query.mockResolvedValue({ exists: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");

      await service.clearSessionError("task-123", "/repo");

      expect(mockTrpcAgent.setConfigOption.mutate).not.toHaveBeenCalled();
    });

    it("keeps the in-memory transcript when the log read returns nothing", async () => {
      const service = getSessionService();
      const previousEvents = [
        {
          type: "acp_message" as const,
          ts: 1,
          message: {
            jsonrpc: "2.0",
            method: "session/update",
            params: {
              update: {
                sessionUpdate: "agent_message_chunk",
                content: { type: "text", text: "Working on it" },
              },
            },
          },
        },
      ];
      const mockSession = createMockSession({
        status: "error",
        logUrl: "https://logs.example.com/run-123",
        events: previousEvents as AgentSession["events"],
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": mockSession,
      });
      mockTrpcAgent.reconnect.mutate.mockResolvedValue({
        sessionId: "run-123",
        channel: "agent-event:run-123",
        configOptions: [],
      });
      mockTrpcAgent.onSessionEvent.subscribe.mockReturnValue({
        unsubscribe: vi.fn(),
      });
      mockTrpcAgent.onPermissionRequest.subscribe.mockReturnValue({
        unsubscribe: vi.fn(),
      });
      mockTrpcWorkspace.verify.query.mockResolvedValue({ exists: true });
      // Both the local cache and S3 reads come back empty (e.g. unreadable
      // log after an agent crash) — the repaint must not blank the transcript.
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");

      await service.clearSessionError("task-123", "/repo");

      const stored = mockSessionStoreSetters.setSession.mock.calls.at(-1)?.[0];
      expect(stored.events).toBe(previousEvents);
    });

    it("carries the queue and its edit hold across an in-place reconnect", async () => {
      const service = getSessionService();
      const queued = [{ id: "q-1", content: "old", queuedAt: 1 }];
      const mockSession = createMockSession({
        status: "error",
        logUrl: "https://logs.example.com/run-123",
        messageQueue: queued,
        editingQueuedId: "q-1",
      });
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": mockSession,
      });
      mockTrpcAgent.reconnect.mutate.mockResolvedValue({
        sessionId: "run-123",
        channel: "agent-event:run-123",
        configOptions: [],
      });
      mockTrpcWorkspace.verify.query.mockResolvedValue({ exists: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcLogs.fetchS3Logs.query.mockResolvedValue("");

      await service.clearSessionError("task-123", "/repo");

      // The rebuilt session must keep the hold with the queue it guards, or
      // the edited message would auto-send in its stale, pre-edit form.
      const stored = mockSessionStoreSetters.setSession.mock.calls.at(-1)?.[0];
      expect(stored.messageQueue).toBe(queued);
      expect(stored.editingQueuedId).toBe("q-1");
    });

    it("creates fresh session when initialPrompt is set (prompt never delivered)", async () => {
      const service = getSessionService();
      const mockSession = createMockSession({
        status: "error",
        initialPrompt: [{ type: "text", text: "fix the bug" }],
      });
      // First call returns the error session, subsequent calls return connected
      mockSessionStoreSetters.getSessionByTaskId
        .mockReturnValueOnce(mockSession)
        .mockReturnValue(
          createMockSession({
            taskRunId: "new-run",
            status: "connected",
          }),
        );
      mockTrpcAgent.start.mutate.mockResolvedValue({
        channel: "agent-event:new-run",
        configOptions: [],
      });
      mockTrpcAgent.onSessionEvent.subscribe.mockReturnValue({
        unsubscribe: vi.fn(),
      });
      mockTrpcAgent.onPermissionRequest.subscribe.mockReturnValue({
        unsubscribe: vi.fn(),
      });
      mockTrpcAgent.prompt.mutate.mockResolvedValue({ stopReason: "end_turn" });
      mockBuildAuthenticatedClient.mockReturnValue({
        ...mockAuthenticatedClient,
        createTaskRun: vi.fn().mockResolvedValue({ id: "new-run" }),
        appendTaskRunLog: vi.fn(),
      });

      await service.clearSessionError("task-123", "/repo");

      // Should tear down old session and create a new one
      expect(mockTrpcAgent.cancel.mutate).toHaveBeenCalledWith({
        sessionId: "run-123",
      });
      expect(mockTrpcAgent.start.mutate).toHaveBeenCalled();
    });

    it("handles missing session gracefully", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(undefined);

      await expect(
        service.clearSessionError("task-123", "/repo"),
      ).resolves.not.toThrow();
    });
  });

  describe("handoffToCloud", () => {
    it("starts GitHub reauth when cloud handoff needs user authorization", async () => {
      const service = getSessionService();
      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(
        createMockSession(),
      );
      mockTrpcHandoff.executeToCloud.mutate.mockResolvedValue({
        success: false,
        code: "github_authorization_required",
        error: "Connect GitHub in your browser, then retry Continue in cloud.",
      });

      await service.handoffToCloud("task-123", "/repo/path");

      expect(
        mockAuthenticatedClient.startGithubUserIntegrationConnect,
      ).toHaveBeenCalledWith(123);
      expect(mockTrpcOs.openExternal.mutate).toHaveBeenCalledWith({
        url: "https://github.com/login/oauth/authorize",
      });
      expect(toast.info).toHaveBeenCalledWith(
        "Connect GitHub to continue in cloud",
        "Complete the authorization in your browser, then click Continue again.",
      );
      expect(toast.error).not.toHaveBeenCalledWith(
        expect.stringContaining("github_authorization_required"),
      );
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        {
          handoffInProgress: false,
          status: "disconnected",
        },
      );
    });
  });

  describe("automatic local recovery", () => {
    it("reconnects automatically after a subscription error", async () => {
      vi.useFakeTimers();
      const service = getSessionService();
      const mockSession = createMockSession({
        status: "connected",
        logUrl: "https://logs.example.com/run-123",
      });

      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": mockSession,
      });
      mockTrpcWorkspace.verify.query.mockResolvedValue({ exists: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcAgent.reconnect.mutate.mockResolvedValue({
        sessionId: "run-123",
        channel: "agent-event:run-123",
        configOptions: [],
      });

      await service.clearSessionError("task-123", "/repo");

      const onError = mockTrpcAgent.onSessionEvent.subscribe.mock.calls[0]?.[1]
        ?.onError as ((error: Error) => void) | undefined;
      expect(onError).toBeDefined();

      onError?.(new Error("connection dropped"));
      await vi.runAllTimersAsync();

      expect(mockTrpcAgent.reconnect.mutate).toHaveBeenCalledTimes(2);
      expect(mockSessionStoreSetters.updateSession).toHaveBeenCalledWith(
        "run-123",
        expect.objectContaining({
          status: "disconnected",
          errorMessage: expect.stringContaining("Reconnecting"),
        }),
      );

      vi.useRealTimers();
    });

    it("shows the error screen only after automatic reconnect attempts fail", async () => {
      vi.useFakeTimers();
      const service = getSessionService();
      const mockSession = createMockSession({
        status: "connected",
        logUrl: "https://logs.example.com/run-123",
      });

      mockSessionStoreSetters.getSessionByTaskId.mockReturnValue(mockSession);
      mockSessionStoreSetters.getSessions.mockReturnValue({
        "run-123": mockSession,
      });
      mockTrpcWorkspace.verify.query.mockResolvedValue({ exists: true });
      mockTrpcLogs.readLocalLogs.query.mockResolvedValue("");
      mockTrpcAgent.reconnect.mutate
        .mockResolvedValueOnce({
          sessionId: "run-123",
          channel: "agent-event:run-123",
          configOptions: [],
        })
        .mockResolvedValue(null);

      await service.clearSessionError("task-123", "/repo");

      const onError = mockTrpcAgent.onSessionEvent.subscribe.mock.calls[0]?.[1]
        ?.onError as ((error: Error) => void) | undefined;
      expect(onError).toBeDefined();

      onError?.(new Error("connection dropped"));
      await vi.runAllTimersAsync();

      expect(mockTrpcAgent.reconnect.mutate).toHaveBeenCalledTimes(4);
      expect(mockSessionStoreSetters.setSession).toHaveBeenCalledWith(
        expect.objectContaining({
          status: "error",
          errorTitle: "Connection lost",
          errorMessage: expect.any(String),
        }),
      );

      vi.useRealTimers();
    });
  });
});

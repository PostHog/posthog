import type { HandoffHost } from "@posthog/shared";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { extractHandoffErrorCode, HandoffService } from "./handoff";
import type { HandoffPreflightInput } from "./schemas";

const DEFAULT_LOCAL_GIT_STATE = {
  head: "abc123",
  branch: "main",
  upstreamHead: "def456",
  upstreamRemote: "origin",
  upstreamMergeRef: "refs/heads/main",
};

function createService(hostOverrides: Partial<HandoffHost> = {}): {
  service: HandoffService;
  host: HandoffHost;
} {
  const host = {
    getChangedFiles: vi.fn().mockResolvedValue([]),
    getLocalGitState: vi.fn().mockResolvedValue(DEFAULT_LOCAL_GIT_STATE),
    markRunEnvironmentLocal: vi.fn(),
    fetchResumeState: vi.fn(),
    formatConversation: vi.fn(),
    applyGitCheckpoint: vi.fn(),
    reconnectSession: vi.fn(),
    attachWorkspaceToFolder: vi.fn(),
    seedLocalLogs: vi.fn(),
    setPendingContext: vi.fn(),
    killSession: vi.fn(),
    updateWorkspaceMode: vi.fn(),
    captureGitCheckpoint: vi.fn(),
    persistCheckpointToLog: vi.fn(),
    countLocalLogEntries: vi.fn(),
    resumeRunInCloud: vi.fn(),
    cleanupLocalAfterCloudHandoff: vi.fn(),
    deleteLocalLogCache: vi.fn(),
    ...hostOverrides,
  } as unknown as HandoffHost;
  const cloudTaskService = { sendCommand: vi.fn() } as never;
  const scopedLogger = {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  };
  const logger = { ...scopedLogger, scope: () => scopedLogger } as never;

  return { service: new HandoffService(host, cloudTaskService, logger), host };
}

function createPreflightInput(
  overrides: Partial<HandoffPreflightInput> = {},
): HandoffPreflightInput {
  return {
    taskId: "task-1",
    runId: "run-1",
    repoPath: "/repo/path",
    apiHost: "https://us.posthog.com",
    teamId: 2,
    ...overrides,
  };
}

describe("HandoffService.preflight", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns canHandoff=true when working tree is clean", async () => {
    const { service } = createService();
    const result = await service.preflight(createPreflightInput());

    expect(result.canHandoff).toBe(true);
    expect(result.localTreeDirty).toBe(false);
    expect(result.reason).toBeUndefined();
    expect(result.localGitState).toEqual(DEFAULT_LOCAL_GIT_STATE);
  });

  it("returns canHandoff=false when working tree has changes", async () => {
    const { service } = createService({
      getChangedFiles: vi
        .fn()
        .mockResolvedValue([{ path: "src/index.ts", status: "modified" }]),
    });
    const result = await service.preflight(createPreflightInput());

    expect(result.canHandoff).toBe(false);
    expect(result.localTreeDirty).toBe(true);
    expect(result.reason).toContain("uncommitted changes");
  });

  it("checks the correct repo path", async () => {
    const { service, host } = createService();
    await service.preflight(createPreflightInput({ repoPath: "/custom/path" }));

    expect(host.getChangedFiles).toHaveBeenCalledWith("/custom/path");
  });

  it("returns canHandoff=true when git check throws", async () => {
    const { service } = createService({
      getChangedFiles: vi.fn().mockRejectedValue(new Error("git not found")),
    });
    const result = await service.preflight(createPreflightInput());

    expect(result.canHandoff).toBe(true);
    expect(result.localTreeDirty).toBe(false);
  });
});

describe("extractHandoffErrorCode", () => {
  it("detects GitHub authorization failures in backend error payloads", () => {
    const message =
      'Failed request: [400] {"type":"validation_error","code":"github_authorization_required","detail":"Link a GitHub account"}';

    expect(extractHandoffErrorCode(message)).toBe(
      "github_authorization_required",
    );
  });

  it("ignores unrelated failures", () => {
    expect(extractHandoffErrorCode("Failed request: [500] boom")).toBe(
      undefined,
    );
  });
});

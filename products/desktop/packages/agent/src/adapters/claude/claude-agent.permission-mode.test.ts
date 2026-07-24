import type { AgentSideConnection } from "@agentclientprotocol/sdk";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  CODE_EXECUTION_MODES,
  type CodeExecutionMode,
} from "../../execution-mode";
import { createMockQuery, type MockQuery } from "../../test/mocks/claude-sdk";
import { Pushable } from "../../utils/streams";
import { toSdkPermissionMode } from "./tools";

vi.mock("@anthropic-ai/claude-agent-sdk", () => ({
  query: vi.fn(),
}));

vi.mock("./mcp/tool-metadata", () => ({
  fetchMcpToolMetadata: vi.fn().mockResolvedValue(undefined),
  getConnectedMcpServerNames: vi.fn().mockReturnValue([]),
  setMcpToolApprovalStates: vi.fn(),
  isMcpToolReadOnly: vi.fn().mockReturnValue(false),
  getMcpToolMetadata: vi.fn().mockReturnValue(undefined),
  getMcpToolApprovalState: vi.fn().mockReturnValue(undefined),
}));

const { ClaudeAcpAgent } = await import("./claude-agent");
type Agent = InstanceType<typeof ClaudeAcpAgent>;

interface ClientMocks {
  sessionUpdate: ReturnType<typeof vi.fn>;
  extNotification: ReturnType<typeof vi.fn>;
}

function makeAgent(): { agent: Agent; client: ClientMocks } {
  const client: ClientMocks = {
    sessionUpdate: vi.fn().mockResolvedValue(undefined),
    extNotification: vi.fn().mockResolvedValue(undefined),
  };
  const agent = new ClaudeAcpAgent(client as unknown as AgentSideConnection);
  return { agent, client };
}

function installFakeSession(
  agent: Agent,
  sessionId: string,
  permissionMode: CodeExecutionMode = "default",
): MockQuery {
  const query = createMockQuery();
  const input = new Pushable();
  const abortController = new AbortController();

  const session = {
    query,
    queryOptions: { sessionId, cwd: "/tmp/repo", abortController },
    buildInProcessMcpServers: () => ({}),
    localToolsServerNames: [] as string[],
    input,
    cancelled: false,
    interruptReason: undefined,
    settingsManager: { dispose: vi.fn(), getRepoRoot: () => "/tmp/repo" },
    permissionMode,
    abortController,
    accumulatedUsage: {
      inputTokens: 0,
      outputTokens: 0,
      cachedReadTokens: 0,
      cachedWriteTokens: 0,
    },
    sessionResources: new Set(),
    configOptions: [],
    turnQueue: [],
    activeTurn: null,
    pendingOrphanResults: 0,
    queryGeneration: 0,
    cwd: "/tmp/repo",
    notificationHistory: [] as unknown[],
    taskRunId: "run-1",
    lastContextWindowSize: 200_000,
    modelId: "claude-sonnet-4-6",
    knownSlashCommands: undefined,
  };

  (agent as unknown as { session: typeof session }).session = session;
  (agent as unknown as { sessionId: string }).sessionId = sessionId;

  return query;
}

describe("ClaudeAcpAgent.setSessionMode — SDK permission-mode translation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it.each(CODE_EXECUTION_MODES)(
    "maps modeId %s to the SDK's permission mode at the setPermissionMode call site",
    async (modeId) => {
      const { agent } = makeAgent();
      const query = installFakeSession(agent, "s-mode");

      await agent.setSessionMode({ sessionId: "s-mode", modeId });

      expect(query.setPermissionMode).toHaveBeenCalledWith(
        toSdkPermissionMode(modeId),
      );
      expect(
        (agent as unknown as { session: { permissionMode: string } }).session
          .permissionMode,
      ).toBe(modeId);
    },
  );

  it("reverts session.permissionMode to the previous mode when the SDK rejects", async () => {
    const { agent } = makeAgent();
    const query = installFakeSession(agent, "s-mode", "default");
    vi.mocked(query.setPermissionMode).mockRejectedValueOnce(
      new Error("sdk rejected"),
    );

    await expect(
      agent.setSessionMode({ sessionId: "s-mode", modeId: "auto" }),
    ).rejects.toThrow("sdk rejected");

    expect(
      (agent as unknown as { session: { permissionMode: string } }).session
        .permissionMode,
    ).toBe("default");
  });

  it("falls back to a generic error message when the SDK rejection has none", async () => {
    const { agent } = makeAgent();
    const query = installFakeSession(agent, "s-mode", "default");
    vi.mocked(query.setPermissionMode).mockRejectedValueOnce(new Error());

    await expect(
      agent.setSessionMode({ sessionId: "s-mode", modeId: "auto" }),
    ).rejects.toThrow("Invalid Mode");
  });

  it("records modeBeforePlan using the host mode, unaffected by the SDK translation", async () => {
    const { agent } = makeAgent();
    installFakeSession(agent, "s-mode", "auto");

    await agent.setSessionMode({ sessionId: "s-mode", modeId: "plan" });

    const session = (
      agent as unknown as {
        session: { permissionMode: string; modeBeforePlan?: string };
      }
    ).session;
    expect(session.permissionMode).toBe("plan");
    expect(session.modeBeforePlan).toBe("auto");
  });
});

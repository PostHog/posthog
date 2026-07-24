import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import type { AgentSideConnection } from "@agentclientprotocol/sdk";
import type { HookInput, Options } from "@anthropic-ai/claude-agent-sdk";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_GATEWAY_MODEL } from "../../gateway-models";

type SdkQueryHandle = {
  interrupt: ReturnType<typeof vi.fn>;
  setModel: ReturnType<typeof vi.fn>;
  setMcpServers: ReturnType<typeof vi.fn>;
  applyFlagSettings: ReturnType<typeof vi.fn>;
  supportedCommands: ReturnType<typeof vi.fn>;
  initializationResult: ReturnType<typeof vi.fn>;
  close: ReturnType<typeof vi.fn>;
  [Symbol.asyncIterator]: () => AsyncIterator<never>;
};

let nextInitPromise: Promise<unknown> = Promise.resolve({
  result: "success",
  commands: [],
  models: [],
});

function makeQueryHandle(): SdkQueryHandle {
  return {
    interrupt: vi.fn().mockResolvedValue(undefined),
    setModel: vi.fn().mockResolvedValue(undefined),
    setMcpServers: vi.fn().mockResolvedValue(undefined),
    applyFlagSettings: vi.fn().mockResolvedValue(undefined),
    supportedCommands: vi.fn().mockResolvedValue([]),
    initializationResult: vi.fn().mockImplementation(() => nextInitPromise),
    close: vi.fn(),
    [Symbol.asyncIterator]: async function* () {
      /* never yields */
    } as never,
  };
}

const createdQueries: SdkQueryHandle[] = [];
const createdQueryOptions: Options[] = [];

vi.mock("@anthropic-ai/claude-agent-sdk", () => ({
  query: vi.fn(({ options }: { options: Options }) => {
    const handle = makeQueryHandle();
    createdQueries.push(handle);
    createdQueryOptions.push(options);
    return handle;
  }),
  getSessionMessages: vi.fn().mockResolvedValue([]),
  listSessions: vi.fn().mockResolvedValue([]),
  createSdkMcpServer: vi.fn(() => ({
    type: "sdk",
    name: "stub",
    instance: {},
  })),
  tool: vi.fn(),
}));

vi.mock("./mcp/tool-metadata", () => ({
  fetchMcpToolMetadata: vi.fn().mockResolvedValue(undefined),
  getConnectedMcpServerNames: vi.fn().mockReturnValue([]),
  setMcpToolApprovalStates: vi.fn(),
  getMcpToolApprovalState: vi.fn().mockReturnValue("approved"),
  getMcpToolMetadata: vi.fn().mockReturnValue(undefined),
}));

// Import after the mocks so ClaudeAcpAgent resolves the mocked SDK
const { ClaudeAcpAgent } = await import("./claude-agent");
type Agent = InstanceType<typeof ClaudeAcpAgent>;

function makeAgent(): Agent {
  const client = {
    sessionUpdate: vi.fn().mockResolvedValue(undefined),
    extNotification: vi.fn().mockResolvedValue(undefined),
  } as unknown as AgentSideConnection;
  return new ClaudeAcpAgent(client);
}

function getModelConfigOption(response: {
  configOptions?: Array<{ id: string; currentValue?: unknown }> | null;
}) {
  return response.configOptions?.find((opt) => opt.id === "model");
}

// Real temp dirs: createSession validates cwd and SettingsManager reads
// settings from disk; CLAUDE_CONFIG_DIR keeps both away from the real home.
const cwd = mkdtempSync(path.join(os.tmpdir(), "claude-agent-test-cwd-"));
const configDir = mkdtempSync(
  path.join(os.tmpdir(), "claude-agent-test-config-"),
);
const permissionCwd = mkdtempSync(
  path.join(os.tmpdir(), "claude-agent-permission-test-cwd-"),
);
mkdirSync(path.join(permissionCwd, ".claude"), { recursive: true });
writeFileSync(
  path.join(permissionCwd, ".claude", "settings.json"),
  JSON.stringify({ permissions: { allow: ["mcp__posthog__exec"] } }),
);
const savedEnv = {
  ANTHROPIC_BASE_URL: process.env.ANTHROPIC_BASE_URL,
  CLAUDE_CONFIG_DIR: process.env.CLAUDE_CONFIG_DIR,
};

afterAll(() => {
  rmSync(cwd, { recursive: true, force: true });
  rmSync(configDir, { recursive: true, force: true });
  rmSync(permissionCwd, { recursive: true, force: true });
  process.env.ANTHROPIC_BASE_URL = savedEnv.ANTHROPIC_BASE_URL;
  process.env.CLAUDE_CONFIG_DIR = savedEnv.CLAUDE_CONFIG_DIR;
  if (savedEnv.ANTHROPIC_BASE_URL === undefined) {
    delete process.env.ANTHROPIC_BASE_URL;
  }
  if (savedEnv.CLAUDE_CONFIG_DIR === undefined) {
    delete process.env.CLAUDE_CONFIG_DIR;
  }
});

describe("ClaudeAcpAgent session creation", () => {
  beforeEach(() => {
    createdQueries.length = 0;
    createdQueryOptions.length = 0;
    nextInitPromise = Promise.resolve({
      result: "success",
      commands: [],
      models: [],
    });
    // No gateway: fetchGatewayModels returns [] and the requested model is
    // kept as a custom option — mirrors the gateway-outage failure mode.
    delete process.env.ANTHROPIC_BASE_URL;
    process.env.CLAUDE_CONFIG_DIR = configDir;
  });

  async function runPostHogExecPreToolUse(
    options: Options,
    subTool: string,
  ): Promise<string | undefined> {
    const input = {
      session_id: "permission-session",
      transcript_path: "/tmp/transcript",
      cwd: permissionCwd,
      hook_event_name: "PreToolUse",
      tool_name: "mcp__posthog__exec",
      tool_use_id: "toolu_permission",
      tool_input: { command: `call ${subTool} {}` },
    } as HookInput;

    for (const hook of (options.hooks?.PreToolUse ?? []).flatMap(
      (entry) => entry.hooks ?? [],
    )) {
      const result = await hook(input, undefined, {
        signal: new AbortController().signal,
      });
      const decision = (
        result as {
          hookSpecificOutput?: { permissionDecision?: string };
        }
      ).hookSpecificOutput?.permissionDecision;
      if (decision) return decision;
    }

    return undefined;
  }

  it.each(["new", "resume", "load"] as const)(
    "uses the default PostHog exec permission regex for local %s sessions when metadata omits it",
    async (sessionKind) => {
      const agent = makeAgent();
      const sessionIds = {
        new: "0197a000-0000-7000-8000-000000000101",
        resume: "0197a000-0000-7000-8000-000000000102",
        load: "0197a000-0000-7000-8000-000000000103",
      };
      const params = {
        sessionId: sessionIds[sessionKind],
        cwd: permissionCwd,
        mcpServers: [],
        _meta: { taskRunId: `run-permission-${sessionKind}` },
      };

      if (sessionKind === "new") {
        await agent.newSession(params);
      } else if (sessionKind === "resume") {
        await agent.resumeSession(params);
      } else {
        await agent.loadSession(params);
      }

      expect(createdQueryOptions).toHaveLength(1);
      await expect(
        runPostHogExecPreToolUse(
          createdQueryOptions[0] as Options,
          "dashboard-update",
        ),
      ).resolves.toBe("ask");
    },
  );

  it("uses an explicit PostHog exec permission regex instead of the default", async () => {
    const agent = makeAgent();

    await agent.newSession({
      cwd: permissionCwd,
      mcpServers: [],
      _meta: {
        taskRunId: "run-permission-custom",
        posthogExecPermissionRegex: "(^|-)archive(-|$)",
      },
    });

    expect(createdQueryOptions).toHaveLength(1);
    await expect(
      runPostHogExecPreToolUse(
        createdQueryOptions[0] as Options,
        "dashboard-update",
      ),
    ).resolves.toBe("allow");
    await expect(
      runPostHogExecPreToolUse(
        createdQueryOptions[0] as Options,
        "dashboard-archive",
      ),
    ).resolves.toBe("ask");
  });

  it.each(["[", ""])(
    "warns and falls back to the default regex when metadata carries the invalid regex %j",
    async (posthogExecPermissionRegex) => {
      const agent = makeAgent();
      const warnSpy = vi.spyOn(agent.logger, "warn");

      await agent.newSession({
        cwd: permissionCwd,
        mcpServers: [],
        _meta: {
          taskRunId: "run-permission-invalid",
          posthogExecPermissionRegex,
        },
      });

      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining("Invalid posthogExecPermissionRegex"),
        expect.anything(),
      );
      expect(createdQueryOptions).toHaveLength(1);
      await expect(
        runPostHogExecPreToolUse(
          createdQueryOptions[0] as Options,
          "dashboard-update",
        ),
      ).resolves.toBe("ask");
      await expect(
        runPostHogExecPreToolUse(
          createdQueryOptions[0] as Options,
          "dashboard-get",
        ),
      ).resolves.toBe("allow");
    },
  );

  it.each([
    { environment: "local", expectedCloudMode: false },
    { environment: "cloud", expectedCloudMode: true },
  ] as const)(
    "records $environment sessions as cloudMode=$expectedCloudMode",
    async ({ environment, expectedCloudMode }) => {
      const agent = makeAgent();

      await agent.newSession({
        cwd,
        mcpServers: [],
        _meta: { environment, taskRunId: `run-${environment}` },
      });

      expect(
        (agent as unknown as { session: { cloudMode: boolean } }).session
          .cloudMode,
      ).toBe(expectedCloudMode);
    },
  );

  // The SDK does not carry the model across resume — without an explicit
  // setModel the resumed session silently runs the SDK default (opus).
  it.each([
    {
      name: "applies meta.model to the SDK when resuming",
      sessionId: "0197a000-0000-7000-8000-000000000001",
      model: "claude-fable-5",
      expectedSetModel: "claude-fable-5",
      expectedCurrentValue: "claude-fable-5",
    },
    {
      name: "pins the default model explicitly when resuming without meta.model",
      sessionId: "0197a000-0000-7000-8000-000000000002",
      model: undefined,
      expectedSetModel: "opus",
      expectedCurrentValue: "claude-opus-4-8",
    },
  ])(
    "$name",
    async ({ sessionId, model, expectedSetModel, expectedCurrentValue }) => {
      const agent = makeAgent();

      const response = await agent.resumeSession({
        sessionId,
        cwd,
        mcpServers: [],
        _meta: { taskRunId: "run-1", model },
      });

      expect(createdQueries).toHaveLength(1);
      expect(createdQueries[0].setModel).toHaveBeenCalledWith(expectedSetModel);
      expect(getModelConfigOption(response)?.currentValue).toBe(
        expectedCurrentValue,
      );
    },
  );

  // New sessions pass the model to the SDK at spawn, never via setModel. The
  // Codex-model row guards the desync that surfaced as "picked gpt-5.5, session
  // ran Opus": a non-Anthropic id on the Claude adapter must fall back to the
  // default AND warn rather than silently masquerade as a deliberate Opus run.
  it.each([
    {
      name: "uses the gateway default and never calls setModel without a requested model",
      model: undefined,
      expectsWarn: false,
    },
    {
      name: "warns and falls back to the default when a Codex model reaches the Claude adapter",
      model: "gpt-5.5",
      expectsWarn: true,
    },
  ])("newSession $name", async ({ model, expectsWarn }) => {
    const agent = makeAgent();
    const warnSpy = vi.spyOn(agent.logger, "warn");

    const response = await agent.newSession({
      cwd,
      mcpServers: [],
      _meta: { taskRunId: "run-new", ...(model ? { model } : {}) },
    });

    expect(createdQueries[0].setModel).not.toHaveBeenCalled();
    expect(getModelConfigOption(response)?.currentValue).toBe(
      DEFAULT_GATEWAY_MODEL,
    );
    if (expectsWarn) {
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining(
          "Incompatible model requested on Claude adapter",
        ),
        expect.objectContaining({ requestedModel: model }),
      );
    } else {
      expect(warnSpy).not.toHaveBeenCalled();
    }
  });

  // The timeout *message* (RequestError "... timed out after ...") is covered
  // by claude-agent.refresh.test.ts. Here we cover the leak fix on the
  // new-session and resume paths: any init failure must close the query so the
  // CLI subprocess can't leak and be multiplied by the retry loop.
  it("closes the query and rethrows when new-session init fails", async () => {
    const failedInit = Promise.reject(new Error("init boom"));
    failedInit.catch(() => {});
    nextInitPromise = failedInit;
    const agent = makeAgent();

    await expect(
      agent.newSession({
        cwd,
        mcpServers: [],
        _meta: { taskRunId: "run-init-fail-new" },
      }),
    ).rejects.toThrow(/init boom/);

    expect(createdQueries[0]?.close).toHaveBeenCalledTimes(1);
  });

  it("closes the query and rethrows when resume init fails", async () => {
    const failedInit = Promise.reject(new Error("resume boom"));
    failedInit.catch(() => {});
    nextInitPromise = failedInit;
    const agent = makeAgent();

    await expect(
      agent.resumeSession({
        sessionId: "0197a000-0000-7000-8000-0000000000ff",
        cwd,
        mcpServers: [],
        _meta: { taskRunId: "run-init-fail-resume" },
      }),
    ).rejects.toThrow(/resume boom/);

    expect(createdQueries[0]?.close).toHaveBeenCalledTimes(1);
  });
});

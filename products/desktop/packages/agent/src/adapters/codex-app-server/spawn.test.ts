import { delimiter, dirname } from "node:path";
import { describe, expect, it, vi } from "vitest";
import type { Logger } from "../../utils/logger";
import {
  buildAppServerArgs,
  SANDBOX_STREAM_IDLE_TIMEOUT_MS,
  spawnCodexAppServerProcess,
} from "./spawn";

const BINARY_PATH = "/bundle/codex";

const mockSpawn = vi.hoisted(() => vi.fn());
const mockExecFileSync = vi.hoisted(() => vi.fn());

vi.mock("node:child_process", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:child_process")>();
  return {
    ...original,
    execFileSync: mockExecFileSync,
    spawn: mockSpawn,
  };
});

vi.mock("node:fs", async (importOriginal) => {
  const original = await importOriginal<typeof import("node:fs")>();
  return {
    ...original,
    existsSync: (path: unknown) =>
      path === "/bundle/codex" || original.existsSync(path as string),
  };
});

describe("buildAppServerArgs", () => {
  it("launches the app-server subcommand routed through the PostHog gateway", () => {
    const args = buildAppServerArgs({
      binaryPath: "/bundle/codex",
      apiBaseUrl: "https://gateway.example/v1",
    });

    expect(args[0]).toBe("app-server");
    // Pin codex's guardian reviewer to the host default so it never calls the
    // gateway-blocked `codex-auto-review` model.
    expect(args).toContain('approvals_reviewer="user"');
    expect(args).toContain('model_provider="posthog"');
    expect(args).toContain(
      'model_providers.posthog.base_url="https://gateway.example/v1"',
    );
    expect(args).toContain('model_providers.posthog.wire_api="responses"');
    expect(args).toContain(
      'model_providers.posthog.env_key="POSTHOG_GATEWAY_API_KEY"',
    );
  });

  it("forwards http headers as a quoted TOML inline table on the posthog provider", () => {
    const args = buildAppServerArgs({
      binaryPath: "/bundle/codex",
      apiBaseUrl: "https://gateway.example/v1",
      httpHeaders: {
        "x-posthog-property-ai_stage": "research",
        "x-posthog-property-team_id": "42",
      },
    });

    expect(args).toContain(
      'model_providers.posthog.http_headers={ "x-posthog-property-ai_stage" = "research", "x-posthog-property-team_id" = "42" }',
    );
  });

  it("quotes $-prefixed posthog property header keys in the TOML table", () => {
    const args = buildAppServerArgs({
      binaryPath: "/bundle/codex",
      apiBaseUrl: "https://gateway.example/v1",
      httpHeaders: { "x-posthog-property-$ai_session_id": "task-123" },
    });

    expect(args).toContain(
      'model_providers.posthog.http_headers={ "x-posthog-property-$ai_session_id" = "task-123" }',
    );
  });

  it("omits http_headers when none are provided or the provider is unset", () => {
    const withoutHeaders = buildAppServerArgs({
      binaryPath: "/bundle/codex",
      apiBaseUrl: "https://gateway.example/v1",
    });
    const withoutProvider = buildAppServerArgs({
      binaryPath: "/bundle/codex",
      httpHeaders: { "x-posthog-property-ai_stage": "research" },
    });

    expect(
      withoutHeaders.some((arg) =>
        arg.startsWith("model_providers.posthog.http_headers="),
      ),
    ).toBe(false);
    expect(
      withoutProvider.some((arg) =>
        arg.startsWith("model_providers.posthog.http_headers="),
      ),
    ).toBe(false);
  });

  it.each([
    ["darwin", 'sandbox_mode="workspace-write"'],
    ["linux", 'sandbox_mode="danger-full-access"'],
    ["win32", 'sandbox_mode="danger-full-access"'],
  ])(
    "on %s spawns with %s (macOS keeps the sandbox engaged so read-only can restrict; cloud/linux avoids the linux-sandbox panic)",
    (platform, expected) => {
      const original = process.platform;
      Object.defineProperty(process, "platform", {
        value: platform,
        configurable: true,
      });
      try {
        const args = buildAppServerArgs({ binaryPath: "/bundle/codex" });
        expect(args).toContain(expected);
        expect(args.filter((a) => a.startsWith("sandbox_mode="))).toHaveLength(
          1,
        );
      } finally {
        Object.defineProperty(process, "platform", {
          value: original,
          configurable: true,
        });
      }
    },
  );

  it("uses the machine account without gateway or user integrations", () => {
    const args = buildAppServerArgs({
      binaryPath: "/bundle/codex",
      useMachineAuth: true,
    });

    expect(args).toContain('model_provider="openai"');
    expect(args).toContain('forced_login_method="chatgpt"');
    expect(args).toContain('history.persistence="none"');
    expect(args).toContain("mcp_servers={}");
    expect(args).toContain("hooks={}");
    expect(args).toContain("notify=[]");
    expect(args).toContain('otel.exporter="none"');
    expect(args).not.toContain('cli_auth_credentials_store="file"');
    expect(args.some((arg) => arg.includes("POSTHOG_GATEWAY_API_KEY"))).toBe(
      false,
    );
  });

  it("keeps codex credential stores on files so the bundled binary never triggers keychain prompts", () => {
    const args = buildAppServerArgs({ binaryPath: "/bundle/codex" });

    expect(args).toContain('cli_auth_credentials_store="file"');
    expect(args).toContain('mcp_oauth_credentials_store="file"');
  });

  it("renders configOverrides bare for numbers and quoted for strings", () => {
    const args = buildAppServerArgs({
      binaryPath: "/bundle/codex",
      configOverrides: {
        auto_compact_token_limit: 16000,
        model_verbosity: "low",
      },
    });

    expect(args).toContain("auto_compact_token_limit=16000");
    expect(args).toContain('model_verbosity="low"');
  });

  it("shortens the gateway stream idle timeout only in cloud sandboxes", () => {
    const idleTimeoutArg = `model_providers.posthog.stream_idle_timeout_ms=${SANDBOX_STREAM_IDLE_TIMEOUT_MS}`;
    const options = {
      binaryPath: "/bundle/codex",
      apiBaseUrl: "https://gateway.example/v1",
    };

    expect(buildAppServerArgs(options, { IS_SANDBOX: "1" })).toContain(
      idleTimeoutArg,
    );
    expect(buildAppServerArgs(options, {})).not.toContain(idleTimeoutArg);
  });

  it("pins the cloud BASH_ENV into tool shells for secondary checkouts", () => {
    const args = buildAppServerArgs(
      { binaryPath: "/bundle/codex" },
      { IS_SANDBOX: "1", BASH_ENV: "/tmp/agentsh-bash-env.sh" },
    );

    expect(args).toContain(
      'shell_environment_policy.set.BASH_ENV="/tmp/agentsh-bash-env.sh"',
    );
  });

  it("does not override BASH_ENV outside a managed sandbox", () => {
    const args = buildAppServerArgs(
      { binaryPath: "/bundle/codex" },
      { BASH_ENV: "/Users/example/.bash-env" },
    );

    expect(
      args.some((arg) =>
        arg.startsWith("shell_environment_policy.set.BASH_ENV="),
      ),
    ).toBe(false);
  });

  it("does not set instructions at spawn (developer_instructions are per-thread)", () => {
    const args = buildAppServerArgs({
      binaryPath: "/bundle/codex",
      developerInstructions: "Follow PostHog rules.",
    });

    expect(args.some((arg) => arg.startsWith("developer_instructions="))).toBe(
      false,
    );
    expect(args.some((arg) => arg.startsWith("instructions="))).toBe(false);
  });
});

describe("spawnCodexAppServerProcess", () => {
  const silentLogger = {
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  } as unknown as Logger;

  function fakeChild() {
    return {
      pid: 4242,
      stdin: { destroy: vi.fn() },
      stdout: { destroy: vi.fn() },
      stderr: { on: vi.fn(), destroy: vi.fn() },
      on: vi.fn(),
      kill: vi.fn(),
    };
  }

  it("prefixes the binary dir onto an otherwise untouched PATH and scrubs electron vars", () => {
    const saved = {
      runAsNode: process.env.ELECTRON_RUN_AS_NODE,
      noAsar: process.env.ELECTRON_NO_ASAR,
      path: process.env.PATH,
    };
    process.env.ELECTRON_RUN_AS_NODE = "1";
    process.env.ELECTRON_NO_ASAR = "1";
    mockSpawn.mockReturnValue(fakeChild() as never);
    try {
      spawnCodexAppServerProcess({
        binaryPath: BINARY_PATH,
        logger: silentLogger,
      });

      const env = mockSpawn.mock.calls[0][2].env as NodeJS.ProcessEnv;
      expect(env.PATH).toBe(
        `${dirname(BINARY_PATH)}${delimiter}${saved.path ?? ""}`,
      );
      expect(env.ELECTRON_RUN_AS_NODE).toBeUndefined();
      expect(env.ELECTRON_NO_ASAR).toBeUndefined();
    } finally {
      restoreEnv("ELECTRON_RUN_AS_NODE", saved.runAsNode);
      restoreEnv("ELECTRON_NO_ASAR", saved.noAsar);
      restoreEnv("PATH", saved.path);
    }
  });

  it("separates machine login variables from gateway login variables", () => {
    const saved = {
      access: process.env.CODEX_ACCESS_TOKEN,
      gateway: process.env.POSTHOG_GATEWAY_API_KEY,
      openai: process.env.OPENAI_API_KEY,
      openaiBaseUrl: process.env.OPENAI_BASE_URL,
      sqliteHome: process.env.CODEX_SQLITE_HOME,
    };
    process.env.CODEX_ACCESS_TOKEN = "old-access-token";
    process.env.POSTHOG_GATEWAY_API_KEY = "old-gateway-key";
    process.env.OPENAI_API_KEY = "old-openai-key";
    process.env.OPENAI_BASE_URL = "https://api.openai.example/v1";
    mockSpawn.mockReturnValue(fakeChild() as never);
    try {
      spawnCodexAppServerProcess({
        binaryPath: BINARY_PATH,
        codexHome: "/appdata/codex/run-1",
        useMachineAuth: true,
        logger: silentLogger,
      });
      const subscriptionEnv = mockSpawn.mock.lastCall?.[2]
        .env as NodeJS.ProcessEnv;
      expect(subscriptionEnv.POSTHOG_GATEWAY_API_KEY).toBeUndefined();
      expect(subscriptionEnv.OPENAI_API_KEY).toBeUndefined();
      expect(subscriptionEnv.CODEX_ACCESS_TOKEN).toBeUndefined();
      expect(subscriptionEnv.CODEX_SQLITE_HOME).toBe("/appdata/codex/run-1");

      spawnCodexAppServerProcess({
        binaryPath: BINARY_PATH,
        apiKey: "phk",
        codexHome: "/appdata/codex/run-2",
        logger: silentLogger,
      });
      const gatewayEnv = mockSpawn.mock.lastCall?.[2].env as NodeJS.ProcessEnv;
      expect(gatewayEnv.POSTHOG_GATEWAY_API_KEY).toBe("phk");
      expect(gatewayEnv.OPENAI_API_KEY).toBeUndefined();
      expect(gatewayEnv.OPENAI_BASE_URL).toBeUndefined();
      expect(gatewayEnv.CODEX_ACCESS_TOKEN).toBeUndefined();
      expect(gatewayEnv.CODEX_HOME).toBe("/appdata/codex/run-2");
      expect(gatewayEnv.CODEX_SQLITE_HOME).toBe("/appdata/codex/run-2");
    } finally {
      restoreEnv("CODEX_ACCESS_TOKEN", saved.access);
      restoreEnv("POSTHOG_GATEWAY_API_KEY", saved.gateway);
      restoreEnv("OPENAI_API_KEY", saved.openai);
      restoreEnv("OPENAI_BASE_URL", saved.openaiBaseUrl);
      restoreEnv("CODEX_SQLITE_HOME", saved.sqliteHome);
    }
  });

  // Codex snapshots process.env at spawn time, so the per-session mount must
  // win over conflicting global values, and a session without a publish token
  // (impersonation) must not inherit another session's.
  it("applies the per-session context wiki over conflicting process.env and scrubs a missing token", () => {
    const saved = {
      wikiPath: process.env.POSTHOG_CONTEXT_LAYER_PATH,
      commitsPath: process.env.POSTHOG_CONTEXT_LAYER_COMMITS_PATH,
      personalKey: process.env.POSTHOG_PERSONAL_API_KEY,
    };
    process.env.POSTHOG_CONTEXT_LAYER_PATH = "/stale/wiki";
    process.env.POSTHOG_CONTEXT_LAYER_COMMITS_PATH = "/stale/commits";
    process.env.POSTHOG_PERSONAL_API_KEY = "other-sessions-token";
    mockSpawn.mockReturnValue(fakeChild() as never);
    try {
      spawnCodexAppServerProcess({
        binaryPath: BINARY_PATH,
        contextWiki: {
          path: "/wiki/a",
          commitsPath: "/api/organizations/a/context_layer/commits/",
        },
        logger: silentLogger,
      });

      const env = mockSpawn.mock.lastCall?.[2].env as NodeJS.ProcessEnv;
      expect(env.POSTHOG_CONTEXT_LAYER_PATH).toBe("/wiki/a");
      expect(env.POSTHOG_CONTEXT_LAYER_COMMITS_PATH).toBe(
        "/api/organizations/a/context_layer/commits/",
      );
      expect(env.POSTHOG_PERSONAL_API_KEY).toBeUndefined();
    } finally {
      restoreEnv("POSTHOG_CONTEXT_LAYER_PATH", saved.wikiPath);
      restoreEnv("POSTHOG_CONTEXT_LAYER_COMMITS_PATH", saved.commitsPath);
      restoreEnv("POSTHOG_PERSONAL_API_KEY", saved.personalKey);
    }
  });

  it("kills descendant processes before the Codex process on Unix", () => {
    const child = fakeChild();
    const killProcess = vi.spyOn(process, "kill").mockReturnValue(true);
    mockSpawn.mockReturnValue(child as never);
    mockExecFileSync.mockReturnValue(
      "4242 100\n5000 4242\n6000 5000\n5001 4242\n",
    );

    try {
      const spawned = spawnCodexAppServerProcess({
        binaryPath: BINARY_PATH,
        logger: silentLogger,
      });

      spawned.kill();

      expect(killProcess.mock.calls).toEqual([
        [6000, "SIGTERM"],
        [5000, "SIGTERM"],
        [5001, "SIGTERM"],
        [4242, "SIGTERM"],
      ]);
      expect(child.kill).not.toHaveBeenCalled();
    } finally {
      killProcess.mockRestore();
    }
  });

  it("falls back to the direct child when process discovery fails", () => {
    const child = fakeChild();
    mockSpawn.mockReturnValue(child as never);
    mockExecFileSync.mockImplementation(() => {
      throw new Error("ps failed");
    });

    const spawned = spawnCodexAppServerProcess({
      binaryPath: BINARY_PATH,
      logger: silentLogger,
    });

    spawned.kill();

    expect(child.kill).toHaveBeenCalledWith("SIGTERM");
  });
});

function restoreEnv(key: string, value: string | undefined): void {
  if (value === undefined) {
    delete process.env[key];
  } else {
    process.env[key] = value;
  }
}

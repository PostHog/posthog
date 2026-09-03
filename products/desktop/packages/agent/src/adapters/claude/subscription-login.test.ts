import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const spawnMock = vi.hoisted(() => vi.fn());

vi.mock("node:child_process", async () => {
  const actual =
    await vi.importActual<typeof import("node:child_process")>(
      "node:child_process",
    );
  return { ...actual, spawn: spawnMock };
});
vi.mock("node:fs", async () => {
  const actual = await vi.importActual<typeof import("node:fs")>("node:fs");
  return { ...actual, existsSync: vi.fn(actual.existsSync) };
});

import { hasClaudeLogin } from "./subscription-login";

class FakeChildProcess extends EventEmitter {
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  kill = vi.fn();
}

const STRIPPED_KEYS = [
  "ANTHROPIC_BASE_URL",
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_CUSTOM_HEADERS",
  "CLAUDE_CODE_USE_BEDROCK",
  "CLAUDE_CODE_USE_VERTEX",
  "CLAUDE_CODE_USE_FOUNDRY",
  "CLAUDE_CODE_USE_ANTHROPIC_AWS",
  "CLAUDE_CODE_USE_MANTLE",
] as const;

function statusJson(loggedIn: boolean, authMethod: string): string {
  return JSON.stringify({ loggedIn, authMethod });
}

describe("hasClaudeLogin", () => {
  const original: Partial<Record<string, string | undefined>> = {};
  let child: FakeChildProcess;

  beforeEach(() => {
    vi.mocked(existsSync).mockReturnValue(true);
    child = new FakeChildProcess();
    spawnMock.mockReturnValue(child);
    for (const key of STRIPPED_KEYS) {
      original[key] = process.env[key];
      process.env[key] = `ambient-${key}`;
    }
    process.env.CLAUDE_CODE_OAUTH_TOKEN = "user-oauth-token";
  });

  afterEach(() => {
    vi.clearAllMocks();
    for (const key of STRIPPED_KEYS) {
      const value = original[key];
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
    delete process.env.CLAUDE_CODE_OAUTH_TOKEN;
  });

  function emitStdout(data: string): void {
    queueMicrotask(() => {
      child.stdout.emit("data", Buffer.from(data, "utf8"));
      child.emit("exit", 0);
    });
  }

  function exit(code: number): void {
    queueMicrotask(() => child.emit("exit", code));
  }

  it("reports logged in for a claude.ai subscription", async () => {
    const result = hasClaudeLogin({
      claudeCliPath: "/bundled/claude",
      machineAuth: {},
    });
    emitStdout(statusJson(true, "claude.ai"));
    await expect(result).resolves.toBe("logged-in");
  });

  it("reports logged in for an oauth_token subscription", async () => {
    const result = hasClaudeLogin({
      claudeCliPath: "/bundled/claude",
      machineAuth: {},
    });
    emitStdout(statusJson(true, "oauth_token"));
    await expect(result).resolves.toBe("logged-in");
  });

  it("reports logged out for a third-party Bedrock provider", async () => {
    const result = hasClaudeLogin({
      claudeCliPath: "/bundled/claude",
      machineAuth: {},
    });
    emitStdout(statusJson(true, "third_party"));
    await expect(result).resolves.toBe("logged-out");
  });

  it("reports logged out for an api_key auth method", async () => {
    const result = hasClaudeLogin({
      claudeCliPath: "/bundled/claude",
      machineAuth: {},
    });
    emitStdout(statusJson(true, "api_key"));
    await expect(result).resolves.toBe("logged-out");
  });

  it("reports logged out when the CLI confirms no login", async () => {
    const result = hasClaudeLogin({
      claudeCliPath: "/bundled/claude",
      machineAuth: {},
    });
    emitStdout(statusJson(false, "none"));
    await expect(result).resolves.toBe("logged-out");
  });

  it("reports unknown when the CLI exits non-zero with no JSON", async () => {
    const result = hasClaudeLogin({
      claudeCliPath: "/bundled/claude",
      machineAuth: {},
    });
    exit(1);
    await expect(result).resolves.toBe("unknown");
  });

  it("reports unknown when the CLI cannot start", async () => {
    const result = hasClaudeLogin({
      claudeCliPath: "/bundled/claude",
      machineAuth: {},
    });
    queueMicrotask(() => child.emit("error", new Error("spawn failed")));
    await expect(result).resolves.toBe("unknown");
  });

  it("reports unknown when the bundled binary is missing", async () => {
    vi.mocked(existsSync).mockReturnValue(false);
    await expect(
      hasClaudeLogin({ claudeCliPath: "/bundled/claude", machineAuth: {} }),
    ).resolves.toBe("unknown");
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("spawns the bundled binary with ambient credentials stripped", async () => {
    const result = hasClaudeLogin({
      claudeCliPath: "/bundled/claude",
      machineAuth: {},
    });
    emitStdout(statusJson(true, "claude.ai"));
    await result;

    expect(spawnMock).toHaveBeenCalledTimes(1);
    const [command, args, spawnOptions] = spawnMock.mock.calls[0] as [
      string,
      string[],
      { env: NodeJS.ProcessEnv },
    ];
    expect(command).toBe("/bundled/claude");
    expect(args).toEqual(["auth", "status", "--json"]);
    for (const key of STRIPPED_KEYS) {
      expect(spawnOptions.env[key]).toBeUndefined();
    }
    expect(spawnOptions.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("user-oauth-token");
  });

  it.each([
    { configDir: undefined, expected: path.join(os.homedir(), ".claude") },
    { configDir: "/home/me/.claude", expected: "/home/me/.claude" },
  ])(
    "checks the machine config dir $configDir, not the app one",
    async ({ configDir, expected }) => {
      process.env.CLAUDE_CONFIG_DIR = "/app-data/claude";
      try {
        const result = hasClaudeLogin({
          claudeCliPath: "/bundled/claude",
          machineAuth: { configDir },
        });
        emitStdout(statusJson(true, "claude.ai"));
        await result;

        const [, , spawnOptions] = spawnMock.mock.calls[0] as [
          string,
          string[],
          { env: NodeJS.ProcessEnv },
        ];
        expect(spawnOptions.env.CLAUDE_CONFIG_DIR).toBe(expected);
      } finally {
        delete process.env.CLAUDE_CONFIG_DIR;
      }
    },
  );

  it("runs a legacy cli.js through the current JS runtime", async () => {
    const result = hasClaudeLogin({
      claudeCliPath: "/bundled/claude/cli.js",
      machineAuth: {},
    });
    emitStdout(statusJson(true, "claude.ai"));
    await result;

    const [command, args] = spawnMock.mock.calls[0] as [string, string[]];
    expect(command).toBe(process.execPath);
    expect(args).toEqual([
      "/bundled/claude/cli.js",
      "auth",
      "status",
      "--json",
    ]);
  });

  it.each([
    { exitsAfterTerm: true, expectKill: false },
    { exitsAfterTerm: false, expectKill: true },
  ])(
    "reports unknown on timeout and escalates to SIGKILL only if the CLI ignores SIGTERM (exitsAfterTerm: $exitsAfterTerm)",
    async ({ exitsAfterTerm, expectKill }) => {
      vi.useFakeTimers();
      try {
        const result = hasClaudeLogin({
          claudeCliPath: "/bundled/claude",
          machineAuth: {},
          timeoutMs: 100,
        });
        vi.advanceTimersByTime(200);
        await expect(result).resolves.toBe("unknown");
        expect(child.kill).toHaveBeenCalledWith("SIGTERM");
        if (exitsAfterTerm) child.emit("exit", null);
        vi.advanceTimersByTime(5000);
        expect(child.kill.mock.calls).toEqual(
          expectKill ? [["SIGTERM"], ["SIGKILL"]] : [["SIGTERM"]],
        );
      } finally {
        vi.useRealTimers();
      }
    },
  );
});

import { EventEmitter } from "node:events";
import { existsSync } from "node:fs";
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

import { MACHINE_CLAUDE_CONFIG_DIR_ENV } from "./machine-config-dir";
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
] as const;

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

  function exit(code: number): void {
    queueMicrotask(() => child.emit("exit", code));
  }

  it("reports logged in when `claude auth status` exits 0", async () => {
    const result = hasClaudeLogin({ claudeCliPath: "/bundled/claude" });
    exit(0);
    await expect(result).resolves.toBe(true);
  });

  it("reports logged out when the CLI exits non-zero", async () => {
    const result = hasClaudeLogin({ claudeCliPath: "/bundled/claude" });
    exit(1);
    await expect(result).resolves.toBe(false);
  });

  it("reports logged out when the CLI cannot start", async () => {
    const result = hasClaudeLogin({ claudeCliPath: "/bundled/claude" });
    queueMicrotask(() => child.emit("error", new Error("spawn failed")));
    await expect(result).resolves.toBe(false);
  });

  it("reports logged out when the bundled binary is missing", async () => {
    vi.mocked(existsSync).mockReturnValue(false);
    await expect(
      hasClaudeLogin({ claudeCliPath: "/bundled/claude" }),
    ).resolves.toBe(false);
    expect(spawnMock).not.toHaveBeenCalled();
  });

  it("spawns the bundled binary with ambient credentials stripped", async () => {
    const result = hasClaudeLogin({ claudeCliPath: "/bundled/claude" });
    exit(0);
    await result;

    expect(spawnMock).toHaveBeenCalledTimes(1);
    const [command, args, spawnOptions] = spawnMock.mock.calls[0] as [
      string,
      string[],
      { env: NodeJS.ProcessEnv },
    ];
    expect(command).toBe("/bundled/claude");
    expect(args).toEqual(["auth", "status"]);
    for (const key of STRIPPED_KEYS) {
      expect(spawnOptions.env[key]).toBeUndefined();
    }
    // A user-provided OAuth token is itself a subscription credential — keep it.
    expect(spawnOptions.env.CLAUDE_CODE_OAUTH_TOKEN).toBe("user-oauth-token");
  });

  it.each([
    { machineDir: undefined, expected: undefined },
    { machineDir: "/home/me/.claude", expected: "/home/me/.claude" },
  ])(
    "checks the machine config dir $machineDir, not the app one",
    async ({ machineDir, expected }) => {
      process.env.CLAUDE_CONFIG_DIR = "/app-data/claude";
      if (machineDir) {
        process.env[MACHINE_CLAUDE_CONFIG_DIR_ENV] = machineDir;
      }
      try {
        const result = hasClaudeLogin({ claudeCliPath: "/bundled/claude" });
        exit(0);
        await result;

        const [, , spawnOptions] = spawnMock.mock.calls[0] as [
          string,
          string[],
          { env: NodeJS.ProcessEnv },
        ];
        expect(spawnOptions.env.CLAUDE_CONFIG_DIR).toBe(expected);
        expect(spawnOptions.env[MACHINE_CLAUDE_CONFIG_DIR_ENV]).toBeUndefined();
      } finally {
        delete process.env.CLAUDE_CONFIG_DIR;
        delete process.env[MACHINE_CLAUDE_CONFIG_DIR_ENV];
      }
    },
  );

  it("runs a legacy cli.js through the current JS runtime", async () => {
    const result = hasClaudeLogin({ claudeCliPath: "/bundled/claude/cli.js" });
    exit(0);
    await result;

    const [command, args] = spawnMock.mock.calls[0] as [string, string[]];
    expect(command).toBe(process.execPath);
    expect(args).toEqual(["/bundled/claude/cli.js", "auth", "status"]);
  });

  it("reports logged out when the status check times out", async () => {
    vi.useFakeTimers();
    try {
      const result = hasClaudeLogin({
        claudeCliPath: "/bundled/claude",
        timeoutMs: 100,
      });
      vi.advanceTimersByTime(200);
      await expect(result).resolves.toBe(false);
      expect(child.kill).toHaveBeenCalledWith("SIGTERM");
    } finally {
      vi.useRealTimers();
    }
  });
});

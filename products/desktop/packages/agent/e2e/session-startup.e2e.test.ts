import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ClientSideConnection, ndJsonStream } from "@agentclientprotocol/sdk";
import { query } from "@anthropic-ai/claude-agent-sdk";
import { expect, it, vi } from "vitest";
import { createAcpConnection } from "../src/adapters/acp-connection";
import { withTimeout } from "../src/utils/common";
import { Logger } from "../src/utils/logger";

it("initializes the real Claude process after a setup hook exceeds 30 seconds", async () => {
  const directory = mkdtempSync(join(tmpdir(), "desktop-startup-"));
  mkdirSync(join(directory, ".claude"));
  writeFileSync(
    join(directory, ".claude", "settings.json"),
    JSON.stringify({
      hooks: {
        SessionStart: [
          { hooks: [{ type: "command", command: "sleep 32", timeout: 45 }] },
        ],
      },
    }),
  );
  vi.stubEnv("CLAUDE_CONFIG_DIR", join(directory, "config"));
  vi.stubEnv("ANTHROPIC_API_KEY", "example-not-a-real-key");
  vi.stubEnv("ANTHROPIC_AUTH_TOKEN", "");
  vi.stubEnv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9");
  vi.stubEnv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1");
  const onLog = vi.fn();
  const onNotification = vi.fn();
  const transport = createAcpConnection({
    adapter: "claude",
    deviceType: "local",
    logger: new Logger({ onLog }),
  });
  const connection = new ClientSideConnection(
    () => ({
      sessionUpdate: async () => {},
      extNotification: onNotification,
      requestPermission: async () => ({ outcome: { outcome: "cancelled" } }),
    }),
    ndJsonStream(
      transport.clientStreams.writable,
      transport.clientStreams.readable,
    ),
  );

  try {
    await connection.initialize({ protocolVersion: 1, clientCapabilities: {} });
    const starting = connection.newSession({
      cwd: directory,
      mcpServers: [],
      _meta: {
        environment: "local",
        claudeCode: {
          options: { settingSources: ["project"], includeHookEvents: false },
        },
      },
    });
    await expect(withTimeout(starting, 30_000)).resolves.toEqual({
      result: "timeout",
    });
    const response = await starting;

    expect(response.sessionId).toBeTruthy();
    expect(onNotification).toHaveBeenCalledWith(
      "_posthog/status",
      expect.objectContaining({ status: "setup_hooks" }),
    );
    expect(onNotification).toHaveBeenCalledWith(
      "_posthog/status",
      expect.objectContaining({ status: "sdk_initialization" }),
    );
    expect(onLog).toHaveBeenCalledWith(
      "info",
      "agent:AcpConnection:ClaudeInitialization",
      "Session initialization phase changed",
      expect.objectContaining({
        initializationPhase: "setup_hooks",
      }),
    );
    expect(onLog).toHaveBeenCalledWith(
      "info",
      "agent:AcpConnection:ClaudeInitialization",
      "Session initialized",
      expect.objectContaining({ initMs: expect.any(Number) }),
    );
  } finally {
    await transport.cleanup();
    vi.unstubAllEnvs();
    rmSync(directory, { recursive: true, force: true });
  }
}, 60_000);

it("initializes a cold worktree without running Flox installation", async () => {
  const directory = mkdtempSync(join(tmpdir(), "desktop-cold-worktree-"));
  const worktree = join(directory, "worktree");
  const repository = execFileSync("git", ["rev-parse", "--show-toplevel"], {
    encoding: "utf8",
  }).trim();
  execFileSync(
    "git",
    ["worktree", "add", "--detach", "--no-checkout", worktree, "HEAD"],
    { cwd: repository, stdio: "ignore" },
  );
  const bin = join(directory, "bin");
  mkdirSync(bin);
  const activationMarker = join(directory, "flox-called");
  writeFileSync(
    join(bin, "flox"),
    '#!/bin/sh\nprintf invoked > "$FLOX_TEST_MARKER"\nprintf "PATH=/usr/bin:/bin\\n"\n',
    { mode: 0o755 },
  );
  const abortController = new AbortController();
  const sdkQuery = query({
    prompt: (async function* () {
      await new Promise(() => {});
    })(),
    options: {
      cwd: worktree,
      settingSources: [],
      settings: {
        hooks: {
          SessionStart: [
            { hooks: [{ type: "command", command: 'bash "$FLOX_TEST_HOOK"' }] },
          ],
        },
      },
      tools: [],
      mcpServers: {},
      abortController,
      env: {
        ...process.env,
        PATH: `${bin}:${process.env.PATH}`,
        FLOX_TEST_MARKER: activationMarker,
        FLOX_TEST_HOOK: join(repository, ".claude/hooks/setup-flox.sh"),
        CLAUDE_CONFIG_DIR: join(directory, "config"),
        CLAUDE_CODE_REMOTE: "false",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
        ANTHROPIC_API_KEY: "example-not-a-real-key",
        ANTHROPIC_AUTH_TOKEN: "",
        ANTHROPIC_BASE_URL: "http://127.0.0.1:9",
      },
    },
  });
  try {
    const initialized = await withTimeout(
      sdkQuery.initializationResult(),
      5000,
    );
    expect(initialized.result).toBe("success");
    expect(existsSync(activationMarker)).toBe(false);
  } finally {
    sdkQuery.close();
    abortController.abort();
    execFileSync("git", ["worktree", "remove", "--force", worktree], {
      cwd: repository,
      stdio: "ignore",
    });
    rmSync(directory, { recursive: true, force: true });
  }
}, 15_000);

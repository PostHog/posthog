import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ClientSideConnection, ndJsonStream } from "@agentclientprotocol/sdk";
import { expect, it, vi } from "vitest";
import { createAcpConnection } from "../src/adapters/acp-connection";
import { withTimeout } from "../src/utils/common";
import { Logger } from "../src/utils/logger";

it("runs repository setup in a new worktree beyond the connection deadline", async () => {
  const directory = mkdtempSync(join(tmpdir(), "desktop-startup-"));
  const repository = join(directory, "repository");
  const worktree = join(directory, "worktree");
  const source = execFileSync("git", ["rev-parse", "--show-toplevel"], {
    encoding: "utf8",
  }).trim();
  const settings = JSON.stringify({
    hooks: {
      SessionStart: [
        {
          hooks: [
            {
              type: "command",
              command:
                "printf 'started\\n' >> .setup-runs; if [ ! -f .setup-ready ]; then sleep 32; printf ready > .setup-ready; fi",
              timeout: 45,
            },
          ],
        },
      ],
    },
  });

  try {
    execFileSync(
      "git",
      ["clone", "--shared", "--no-checkout", source, repository],
      {
        stdio: "ignore",
      },
    );
    execFileSync(
      "git",
      ["worktree", "add", "--detach", "--no-checkout", worktree, "HEAD"],
      { cwd: repository, stdio: "ignore" },
    );
    for (const cwd of [repository, worktree]) {
      mkdirSync(join(cwd, ".claude"));
      writeFileSync(join(cwd, ".claude", "settings.json"), settings);
      writeFileSync(join(cwd, ".gitignore"), ".setup-ready\n.setup-runs\n");
    }
    writeFileSync(join(repository, ".setup-ready"), "ready");
    expect(statSync(join(repository, ".git")).isDirectory()).toBe(true);
    expect(statSync(join(worktree, ".git")).isFile()).toBe(true);
    expect(existsSync(join(worktree, ".setup-ready"))).toBe(false);

    vi.stubEnv("CLAUDE_CONFIG_DIR", join(directory, "config"));
    vi.stubEnv("ANTHROPIC_API_KEY", "example-not-a-real-key");
    vi.stubEnv("ANTHROPIC_AUTH_TOKEN", "");
    vi.stubEnv("ANTHROPIC_BASE_URL", "http://127.0.0.1:9");
    vi.stubEnv("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1");

    for (const { cwd, needsSetup } of [
      { cwd: repository, needsSetup: false },
      { cwd: worktree, needsSetup: true },
      { cwd: worktree, needsSetup: false },
    ]) {
      const onLog = vi.fn();
      const onNotification = vi.fn();
      const processExits: Promise<void>[] = [];
      const pendingExits = new Map<number, () => void>();
      const transport = createAcpConnection({
        adapter: "claude",
        deviceType: "local",
        logger: new Logger({ onLog }),
        processCallbacks: {
          onProcessSpawned: ({ pid }) => {
            processExits.push(
              new Promise<void>((resolve) => pendingExits.set(pid, resolve)),
            );
          },
          onProcessExited: (pid) => {
            pendingExits.get(pid)?.();
            pendingExits.delete(pid);
          },
        },
      });
      const connection = new ClientSideConnection(
        () => ({
          sessionUpdate: async () => {},
          extNotification: onNotification,
          requestPermission: async () => ({
            outcome: { outcome: "cancelled" },
          }),
        }),
        ndJsonStream(
          transport.clientStreams.writable,
          transport.clientStreams.readable,
        ),
      );

      try {
        await connection.initialize({
          protocolVersion: 1,
          clientCapabilities: {},
        });
        const starting = connection.newSession({
          cwd,
          mcpServers: [],
          _meta: {
            environment: "local",
            claudeCode: {
              options: {
                settingSources: ["project"],
                includeHookEvents: false,
              },
            },
          },
        });
        const atConnectionDeadline = await withTimeout(starting, 30_000);
        if (needsSetup) {
          expect(atConnectionDeadline).toEqual({ result: "timeout" });
          expect(onNotification).toHaveBeenCalledWith(
            "_posthog/status",
            expect.objectContaining({ status: "setup_hooks" }),
          );
          expect(existsSync(join(cwd, ".setup-ready"))).toBe(false);
        } else {
          expect(atConnectionDeadline.result).toBe("success");
        }
        const response = await starting;

        expect(response.sessionId).toBeTruthy();
        expect(existsSync(join(cwd, ".setup-ready"))).toBe(true);
        expect(
          readFileSync(join(cwd, ".claude", "settings.json"), "utf8"),
        ).toBe(settings);
        expect(onNotification).toHaveBeenCalledWith(
          "_posthog/status",
          expect.objectContaining({ status: "sdk_initialization" }),
        );
        expect(onLog).toHaveBeenCalledWith(
          "info",
          "agent:AcpConnection:ClaudeInitialization",
          "Session initialized",
          expect.objectContaining({ initMs: expect.any(Number) }),
        );
      } finally {
        await transport.cleanup();
        // Aborting the SDK does not wait for its child to stop writing config.
        expect(
          (await withTimeout(Promise.all(processExits), 5_000)).result,
        ).toBe("success");
      }
    }
    expect(readFileSync(join(repository, ".setup-runs"), "utf8")).toBe(
      "started\n",
    );
    expect(readFileSync(join(worktree, ".setup-runs"), "utf8")).toBe(
      "started\nstarted\n",
    );
  } finally {
    vi.unstubAllEnvs();
    rmSync(directory, { recursive: true, force: true });
  }
}, 90_000);

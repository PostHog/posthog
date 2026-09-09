import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ClientSideConnection, ndJsonStream } from "@agentclientprotocol/sdk";
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
  const transport = createAcpConnection({
    adapter: "claude",
    deviceType: "local",
    logger: new Logger({ onLog }),
  });
  const connection = new ClientSideConnection(
    () => ({
      sessionUpdate: async () => {},
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

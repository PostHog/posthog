import { beforeEach, describe, expect, it, vi } from "vitest";

const claudeAgentConstructor = vi.fn();

vi.mock("./claude/claude-agent", () => ({
  ClaudeAcpAgent: class {
    constructor(...args: unknown[]) {
      claudeAgentConstructor(...args);
    }
    // Called by the connection's cleanup.
    async closeSession(): Promise<void> {}
  },
}));

const { createAcpConnection } = await import("./acp-connection");
const { Logger } = await import("../utils/logger");

/**
 * The Claude adapter's own diagnostics include whole payloads: the expanded body
 * of a slash command, raw tool inputs, the subprocess's stderr. A host logger
 * usually carries an `onLog` that persists or transmits what it receives (on
 * desktop, electron-log's file and OTLP transports; on cloud, the run log and
 * the user's task feed), so forwarding is opt-in.
 */
describe("createAcpConnection adapter log forwarding", () => {
  beforeEach(() => {
    claudeAgentConstructor.mockClear();
  });

  function adapterOptions(): { logger?: unknown } {
    // AgentSideConnection builds the agent eagerly, so one call is recorded by
    // the time createAcpConnection returns.
    expect(claudeAgentConstructor).toHaveBeenCalledTimes(1);
    return claudeAgentConstructor.mock.calls[0][1] as { logger?: unknown };
  }

  it("withholds the host logger from the adapter by default", async () => {
    const connection = createAcpConnection({
      adapter: "claude",
      logger: new Logger({ debug: true, onLog: () => {} }),
    });
    try {
      expect(adapterOptions().logger).toBeUndefined();
    } finally {
      await connection.cleanup();
    }
  });

  it("passes a scoped child logger when the host opts in", async () => {
    const connection = createAcpConnection({
      adapter: "claude",
      logger: new Logger({ debug: true, onLog: () => {} }),
      forwardAdapterLogs: true,
    });
    try {
      expect(adapterOptions().logger).toBeInstanceOf(Logger);
    } finally {
      await connection.cleanup();
    }
  });

  it("passes no logger when the host opts in without supplying one", async () => {
    const connection = createAcpConnection({
      adapter: "claude",
      forwardAdapterLogs: true,
    });
    try {
      expect(adapterOptions().logger).toBeUndefined();
    } finally {
      await connection.cleanup();
    }
  });
});

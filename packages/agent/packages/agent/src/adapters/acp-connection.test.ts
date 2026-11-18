import { describe, expect, it, vi } from "vitest";
import type { SessionLogWriter } from "../session-log-writer";
import { Logger } from "../utils/logger";
import { createAcpConnection } from "./acp-connection";
import type { ClaudeAcpAgentOptions } from "./claude/claude-agent";

const agentOptions: (ClaudeAcpAgentOptions | undefined)[] = [];

vi.mock("./claude/claude-agent", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("./claude/claude-agent")>();
  return {
    ...original,
    ClaudeAcpAgent: class extends original.ClaudeAcpAgent {
      constructor(
        client: ConstructorParameters<typeof original.ClaudeAcpAgent>[0],
        options?: ClaudeAcpAgentOptions,
      ) {
        super(client, options);
        agentOptions.push(options);
      }
    },
  };
});

describe("createAcpConnection wire taps", () => {
  it("hands the session log and the broadcast callback the same event id per message", async () => {
    const appendNotification = vi.fn();
    const logWriter = {
      isRegistered: () => true,
      register: vi.fn(),
      appendNotification,
    } as unknown as SessionLogWriter;
    const onWireMessage = vi.fn();

    const connection = createAcpConnection({
      adapter: "claude",
      taskRunId: "run-1",
      taskId: "task-1",
      logWriter,
      onWireMessage,
    });

    const notification = {
      jsonrpc: "2.0",
      method: "_posthog/console",
      params: { level: "info", message: "hello" },
    };
    const writer = connection.clientStreams.writable.getWriter();
    await writer.write(
      new TextEncoder().encode(`${JSON.stringify(notification)}\n`),
    );
    writer.releaseLock();

    expect(appendNotification).toHaveBeenCalledTimes(1);
    expect(onWireMessage).toHaveBeenCalledTimes(1);
    const [, loggedMessage, loggedId] = appendNotification.mock.calls[0];
    const [broadcastMessage, broadcastId] = onWireMessage.mock.calls[0];
    expect(loggedMessage).toEqual(notification);
    expect(broadcastMessage).toBe(loggedMessage);
    expect(loggedId).toBeTruthy();
    expect(broadcastId).toBe(loggedId);

    await connection.cleanup();
  });
});

describe("createAcpConnection claude agent logger", () => {
  it("never gives the agent the session log sink", async () => {
    agentOptions.length = 0;
    const sink: string[] = [];
    const sessionLogger = new Logger({
      debug: true,
      onLog: (_level, _scope, message) => {
        sink.push(message);
      },
    });
    const lines: string[] = [];
    vi.spyOn(console, "info").mockImplementation((line: string) => {
      lines.push(line);
    });

    const connection = createAcpConnection({
      adapter: "claude",
      taskRunId: "run-1",
      taskId: "task-1",
      logger: sessionLogger,
      claudeAgentLogger: new Logger({ level: "info", format: "json" }),
    });
    agentOptions[0]?.logger?.info("from agent");

    expect(sink).not.toContain("from agent");
    expect(lines.map((line) => JSON.parse(line).message)).toEqual([
      "from agent",
    ]);
    await connection.cleanup();
    vi.restoreAllMocks();
  });

  it("leaves the agent on its own logger when none is supplied", async () => {
    agentOptions.length = 0;
    const connection = createAcpConnection({
      adapter: "claude",
      taskRunId: "run-1",
      taskId: "task-1",
      logger: new Logger({ debug: true }),
    });

    expect(agentOptions).toHaveLength(1);
    expect(agentOptions[0]?.logger).toBeUndefined();
    await connection.cleanup();
  });
});

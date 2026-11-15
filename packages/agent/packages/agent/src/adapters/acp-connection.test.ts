import { describe, expect, it, vi } from "vitest";
import type { SessionLogWriter } from "../session-log-writer";
import { createAcpConnection } from "./acp-connection";

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

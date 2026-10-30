import type { PiRpcClient } from "@posthog/agent/pi/rpc-client";
import { describe, expect, it, vi } from "vitest";
import { LocalSession } from "./local";
import { type AgentPrompt, promptReply } from "./prompts";
import { emptyRunView, type RunView } from "./runs";
import { contextFill, shellsStatus } from "./usage";

const emptyView = (): RunView => emptyRunView;

import { transcriptFrom } from "./transcript";

function fakeClient() {
  const send = vi.fn(async (command: { id?: string; type: string }) => ({
    id: command.id,
    type: "response",
    command: command.type,
    success: true,
  }));
  const listeners: {
    event?: (event: unknown) => void;
    permission?: (request: unknown) => void;
  } = {};
  const client = {
    onEvent: (listener: (event: unknown) => void) => {
      listeners.event = listener;
      return () => {};
    },
    onMcpToolPermissionRequest: (listener: (request: unknown) => void) => {
      listeners.permission = listener;
      return () => {};
    },
    respondToExtensionUI: vi.fn(async () => {}),
    respondMcpToolPermission: vi.fn(),
    send,
    start: vi.fn(async () => {}),
    stop: vi.fn(async () => {}),
    getEntries: async () => ({
      entries: [
        {
          type: "message",
          id: "e1",
          message: {
            role: "user",
            content: [{ type: "text", text: "earlier" }],
            timestamp: 1,
          },
        },
      ],
      leafId: null,
    }),
    getCommands: async () => [
      {
        name: "skill:review",
        description: "Review a PR",
        source: "skill",
        sourceInfo: {},
      },
    ],
  };
  return {
    client: client as unknown as PiRpcClient,
    send,
    listeners,
    raw: client,
  };
}

const policies = () => ({ approveMcpTool: vi.fn(async () => {}) });

describe("LocalSession", () => {
  it("shows the saved conversation once started", async () => {
    const { client } = fakeClient();
    const session = new LocalSession(client, policies());
    let view: RunView | null = null;
    session.watch((next) => {
      view = next;
    });

    await session.start();

    expect(view).toMatchObject({ loaded: true, status: "in_progress" });
    expect(
      transcriptFrom("pi", (view as unknown as RunView).entries).lines,
    ).toMatchObject([{ kind: "user", text: "earlier" }]);
  });

  it("reports the model's context window with each turn, so the composer can show the donut", async () => {
    const { client, listeners, raw } = fakeClient();
    Object.assign(raw, {
      getState: async () => ({ model: { contextWindow: 200_000 } }),
    });
    const session = new LocalSession(client, policies());
    let view = emptyView();
    session.watch((next) => {
      view = next;
    });
    await session.start();

    const message = {
      role: "assistant",
      content: [{ type: "text", text: "done" }],
      model: "test-model",
      usage: {
        input: 800,
        output: 100,
        cacheRead: 0,
        cacheWrite: 0,
        totalTokens: 900,
      },
      stopReason: "stop",
      timestamp: 10,
    };
    listeners.event?.({ type: "message_end", message });
    listeners.event?.({
      type: "agent_end",
      messages: [message],
      willRetry: false,
    });
    listeners.event?.({ type: "agent_settled" });

    expect(contextFill(view.entries)).toEqual({ tokens: 900, window: 200_000 });
  });

  it("runs a shell command on this machine and shows it in the chat", async () => {
    const { client, send } = fakeClient();
    send.mockImplementation(async (command) => ({
      id: command.id,
      type: "response",
      command: command.type,
      success: true,
      ...(command.type === "bash"
        ? { data: { output: "clean", exitCode: 0, cancelled: false } }
        : {}),
    }));
    const session = new LocalSession(client, policies());
    let view = emptyView();
    session.watch((next) => {
      view = next;
    });
    await session.start();

    const result = await session.control.bash("git status");

    expect(result).toMatchObject({ output: "clean", exitCode: 0 });
    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({ type: "bash", command: "git status" }),
    );
    const shells = transcriptFrom("pi", view.entries).lines.filter(
      (line) => line.kind === "shell",
    );
    expect(shells).toEqual([
      expect.objectContaining({
        command: "git status",
        status: "completed",
        output: "clean",
      }),
    ]);
  });

  it("sends messages and exposes the run's commands", async () => {
    const { client, send } = fakeClient();
    const session = new LocalSession(client, policies());
    await session.start();

    const image = {
      type: "image" as const,
      data: "aGk=",
      mimeType: "image/png",
    };
    await session.prompt("Fix the flaky test", [image]);

    expect(send).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "prompt",
        message: "Fix the flaky test",
        images: [image],
      }),
    );
    expect(await session.control.commands()).toEqual([
      { name: "skill:review", description: "Review a PR" },
    ]);
  });

  it("keeps the agent's background shell status in its view, as a cloud sandbox logs it", async () => {
    const { client, listeners } = fakeClient();
    const session = new LocalSession(client, policies());
    await session.start();
    let view = emptyView();
    session.watch((next) => {
      view = next;
    });

    listeners.event?.({
      type: "extension_ui_request",
      id: "s1",
      method: "setStatus",
      statusKey: "background-shells",
      statusText: "1 shell · 1 monitor",
    });

    expect(shellsStatus(view.entries)).toBe("1 shell · 1 monitor");
  });

  it("holds the agent's prompts until answered and sends each answer back", async () => {
    const { client, listeners, raw } = fakeClient();
    const approvals = policies();
    const session = new LocalSession(client, approvals);
    let prompts: AgentPrompt[] = [];
    session.watchPrompts((next) => {
      prompts = next;
    });

    listeners.event?.({
      type: "extension_ui_request",
      id: "d1",
      method: "select",
      title: "Pick a branch",
      options: ["main", "dev"],
    });
    listeners.permission?.({
      requestId: "p1",
      serverName: "posthog",
      toolName: "query",
      installationId: "i1",
      arguments: {},
    });
    expect(prompts.map((prompt) => prompt.kind)).toEqual([
      "dialog",
      "permission",
    ]);

    await session.answer(prompts[0], promptReply(prompts[0], 1));
    await session.answer(prompts[0], promptReply(prompts[0], 1));

    expect(raw.respondToExtensionUI).toHaveBeenCalledWith({
      type: "extension_ui_response",
      id: "d1",
      value: "dev",
    });
    expect(approvals.approveMcpTool).toHaveBeenCalledWith("i1", "query");
    expect(raw.respondMcpToolPermission).toHaveBeenCalledWith(
      "p1",
      "allow_always",
    );
    expect(prompts).toEqual([]);
  });
});

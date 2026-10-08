import { TypedEventEmitter } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { ClaudeLocalSession } from "./claudeLocal";
import type { AgentPrompt } from "./prompts";

function fakeAgent() {
  const events = new TypedEventEmitter<Record<string, unknown>>();
  const agent = Object.assign(events, {
    startSession: vi.fn(async () => ({ sessionId: "s1", channel: "c1" })),
    prompt: vi.fn(async () => ({ stopReason: "end_turn" })),
    cancelPrompt: vi.fn(async () => true),
    cancelSession: vi.fn(async () => true),
    respondToPermission: vi.fn(),
    cancelPermission: vi.fn(),
  });
  return agent;
}

const input = {
  taskId: "t1",
  taskRunId: "local-1",
  cwd: "/repo",
  apiHost: "https://us.posthog.com",
  projectId: 7,
};

describe("ClaudeLocalSession", () => {
  it("starts Claude Code on the user's plan in the chat's folder and shows its messages", async () => {
    const agent = fakeAgent();
    const session = new ClaudeLocalSession(
      agent as never,
      { ...input, model: "claude-opus-5-5", effort: "high" },
      async () => true,
    );
    const views: unknown[] = [];
    session.watch((view) => views.push(view));

    await session.start();

    expect(agent.startSession).toHaveBeenCalledWith({
      taskId: "t1",
      taskRunId: "local-1",
      repoPath: "/repo",
      apiHost: "https://us.posthog.com",
      projectId: 7,
      adapter: "claude",
      claudeModelAccess: "own-subscription",
      runMode: "local",
      model: "claude-opus-5-5",
      effort: "high",
    });
    const message = {
      method: "session/update",
      params: { update: { sessionUpdate: "agent_message_chunk" } },
    };
    agent.emit("session-event", {
      taskRunId: "local-1",
      payload: { type: "acp_message", ts: 1, message },
    });
    agent.emit("session-event", {
      taskRunId: "other",
      payload: { type: "acp_message", ts: 2, message },
    });
    const last = views.at(-1) as { entries: { notification: unknown }[] };
    expect(last.entries).toHaveLength(1);
    expect(last.entries[0].notification).toEqual(message);
    expect(session.runtime).toBe("acp");
  });

  it("refuses to start when Claude Code is not logged in, so nothing bills PostHog", async () => {
    const session = new ClaudeLocalSession(
      fakeAgent() as never,
      input,
      async () => false,
    );
    await expect(session.start()).rejects.toThrow(
      "Log in to Claude Code for the TUI first: run `CLAUDE_CONFIG_DIR=~/.claude claude auth login` in a terminal",
    );
  });

  it("sends a message to the session, steering a turn already running", async () => {
    const agent = fakeAgent();
    let finishTurn: (() => void) | undefined;
    agent.prompt.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishTurn = () => resolve({ stopReason: "end_turn" });
        }),
    );
    const session = new ClaudeLocalSession(
      agent as never,
      input,
      async () => true,
    );
    await session.start();

    const first = session.prompt("Fix the test");
    await session.prompt("And the docs");
    finishTurn?.();
    await first;

    expect(agent.prompt).toHaveBeenNthCalledWith(
      1,
      "s1",
      [{ type: "text", text: "Fix the test" }],
      { steer: false },
    );
    expect(agent.prompt).toHaveBeenNthCalledWith(
      2,
      "s1",
      [{ type: "text", text: "And the docs" }],
      { steer: true },
    );
  });

  it("holds a permission request until answered and sends the chosen option back", async () => {
    const agent = fakeAgent();
    const session = new ClaudeLocalSession(
      agent as never,
      input,
      async () => true,
    );
    await session.start();
    const lists: AgentPrompt[][] = [];
    session.watchPrompts((list) => lists.push(list));

    agent.emit("permission-request", {
      taskRunId: "local-1",
      toolCall: { toolCallId: "tc1", title: "Run pnpm test" },
      options: [
        { optionId: "allow", name: "Allow", kind: "allow_once" },
        { optionId: "reject", name: "Reject", kind: "reject_once" },
      ],
    });
    const prompt = lists.at(-1)?.[0];
    expect(prompt?.kind).toBe("acp");
    await session.answer(prompt as AgentPrompt, {
      kind: "acp",
      taskRunId: "local-1",
      toolCallId: "tc1",
      optionId: "allow",
    });

    expect(agent.respondToPermission).toHaveBeenCalledWith(
      "local-1",
      "tc1",
      "allow",
    );
    expect(lists.at(-1)).toEqual([]);
  });

  it("stops the session and its turn", async () => {
    const agent = fakeAgent();
    const session = new ClaudeLocalSession(
      agent as never,
      input,
      async () => true,
    );
    await session.start();
    await session.control.abort();
    await session.stop();
    expect(agent.cancelPrompt).toHaveBeenCalledWith("s1");
    expect(agent.cancelSession).toHaveBeenCalledWith("s1");
  });
});

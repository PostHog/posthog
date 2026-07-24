import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { AgentSessionEvent } from "@posthog/shared/agent-platform-types";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentChatService } from "./agentChatService";
import { agentChatStore } from "./agentChatStore";
import type { AgentChatSession } from "./identifiers";

const INGRESS = "https://ingress.example";
const SLUG = "my-agent";
const SESSION = "sess-1";

const mockClient = vi.hoisted(() => ({
  runAgentSession: vi.fn(),
  streamAgentSession: vi.fn(),
  sendAgentMessage: vi.fn(),
  cancelAgentSession: vi.fn(),
  getAgentApplicationSession: vi.fn(),
  getAgentSessionViaIngress: vi.fn(),
  sendAgentClientToolResult: vi.fn(),
  sendAgentInteractiveToolResult: vi.fn(),
  mintAgentPreviewToken: vi.fn(),
}));
const client = mockClient as unknown as PostHogAPIClient;

function session(chatId: string): AgentChatSession {
  return {
    chatId,
    agentSlug: SLUG,
    ingressBaseUrl: INGRESS,
    revisionId: null,
    createMapper: () => ({
      seedUserMessage: () => [],
      setPromptIdBase: () => {},
      apply: () => [],
    }),
    resolveClientTool: async () => null,
    buildWireText: (text) => text,
    mapConversation: () => [],
  };
}

function ev(kind: AgentSessionEvent["kind"], data: unknown): AgentSessionEvent {
  return {
    kind,
    session_id: SESSION,
    ts: "2026-06-19T00:00:00Z",
    data,
  } as AgentSessionEvent;
}

/** A `/listen` stream that emits the given events then ends cleanly. */
async function* streamOf(...events: AgentSessionEvent[]) {
  for (const e of events) yield e;
}

/** A `/listen` stream that emits, then drops (throws) like a reset/idle close. */
async function* streamThenDrop(...events: AgentSessionEvent[]) {
  for (const e of events) yield e;
  throw new Error("network reset");
}

describe("AgentChatService /listen reconnect", () => {
  let service: AgentChatService;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    service = new AgentChatService();
    mockClient.runAgentSession.mockResolvedValue({ session_id: SESSION });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("reconnects after a dropped tail and finishes on the completed frame", async () => {
    const chatId = "reconnect-ok";
    mockClient.streamAgentSession
      .mockImplementationOnce(() =>
        streamThenDrop(ev("assistant_text", { text: "hi" })),
      )
      .mockImplementationOnce(() => streamOf(ev("completed", {})));

    void service.send(client, session(chatId), "go");
    // Let start() + the first pump (delta then drop) settle, then clear the
    // reconnect backoff so the second attach runs.
    await vi.advanceTimersByTimeAsync(1000);

    expect(mockClient.streamAgentSession).toHaveBeenCalledTimes(2);
    // A live drop never asks the api whether the session ended — the re-attach
    // produced output, so we know it's still going.
    expect(mockClient.getAgentSessionViaIngress).not.toHaveBeenCalled();
    const chat = agentChatStore.getState().chats[chatId];
    expect(chat?.status).toBe("completed");
    expect(chat?.error).toBeNull();
  });

  it("finalizes without an error when the session ended during the gap", async () => {
    const chatId = "terminal-in-gap";
    // Stream drops immediately (no events); the run already finished server-side.
    mockClient.streamAgentSession.mockImplementationOnce(() =>
      streamThenDrop(),
    );
    mockClient.getAgentSessionViaIngress.mockResolvedValue({
      state: "completed",
      conversation: [],
    });

    void service.send(client, session(chatId), "go");
    await vi.advanceTimersByTimeAsync(0);

    // Silent re-attach → we ask the ingress, see it's terminal, and stop. No
    // retry, no error.
    expect(mockClient.getAgentSessionViaIngress).toHaveBeenCalledTimes(1);
    expect(mockClient.streamAgentSession).toHaveBeenCalledTimes(1);
    const chat = agentChatStore.getState().chats[chatId];
    expect(chat?.status).toBe("completed");
    expect(chat?.error).toBeNull();
  });

  it("treats a closed frame as a terminal stream-end", async () => {
    const chatId = "closed";
    let captured: AbortSignal | undefined;
    // A perpetual tail that emits `closed` then would keep yielding: proves the
    // pump stops on `closed` rather than draining the generator.
    async function* perpetual() {
      yield ev("assistant_text_delta", { text: "bye" });
      yield ev("closed", {});
      yield ev("assistant_text_delta", { text: "should never render" });
    }
    mockClient.streamAgentSession.mockImplementationOnce(
      (_url: string, _id: string, signal: AbortSignal) => {
        captured = signal;
        return perpetual();
      },
    );

    void service.send(client, session(chatId), "go");
    await vi.advanceTimersByTimeAsync(0);

    const chat = agentChatStore.getState().chats[chatId];
    expect(chat?.status).toBe("completed");
    expect(chat?.error).toBeNull();
    // No reconnect: the terminal frame ends the tail, so neither the stream nor
    // the liveness probe is re-invoked.
    expect(mockClient.streamAgentSession).toHaveBeenCalledTimes(1);
    expect(mockClient.getAgentSessionViaIngress).not.toHaveBeenCalled();
    // The still-open socket is released on the terminal exit.
    expect(captured?.aborted).toBe(true);
  });

  it("surfaces an error only after the reconnect budget is exhausted", async () => {
    const chatId = "give-up";
    // Always drops with no events; the api keeps reporting the run as live.
    mockClient.streamAgentSession.mockImplementation(() => streamThenDrop());
    mockClient.getAgentSessionViaIngress.mockResolvedValue({
      state: "running",
      conversation: [],
    });

    void service.send(client, session(chatId), "go");
    // Drain the full capped-exponential backoff schedule (≈23.5s).
    await vi.advanceTimersByTimeAsync(30_000);

    // Initial attach + MAX_LISTEN_RECONNECTS (6) re-attaches.
    expect(mockClient.streamAgentSession).toHaveBeenCalledTimes(7);
    const chat = agentChatStore.getState().chats[chatId];
    expect(chat?.error).toBeTruthy();
  });
});

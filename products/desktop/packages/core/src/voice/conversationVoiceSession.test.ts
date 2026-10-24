import "reflect-metadata";
import { ApiRequestError } from "@posthog/api-client/fetcher";
import type { LiveVoiceTransport } from "@posthog/platform/speech";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ConversationVoiceSession,
  type VoiceConversation,
  voiceCommentaryChunks,
} from "./conversationVoiceSession";

function setup() {
  let receive: (data: string) => void = () => {};
  const transport = {
    createOffer: vi.fn(async (handler) => {
      receive = handler;
      return "offer";
    }),
    acceptAnswer: vi.fn(async () => {}),
    send: vi.fn(),
    mute: vi.fn(),
    close: vi.fn(),
  } satisfies LiveVoiceTransport;
  const conversation = {
    createSession: vi.fn(async () => "answer"),
    sendMessage: vi.fn(async () => true),
    onState: vi.fn(),
    onEnded: vi.fn(),
  } satisfies VoiceConversation;
  const session = new ConversationVoiceSession(transport, conversation);
  const emit = (event: object) => receive(JSON.stringify(event));
  const transcript = (
    delta: string,
    start: number,
    end: number,
    id = `${start}`,
  ) =>
    emit({
      type: "session.input_transcript.delta",
      event_id: id,
      delta,
      start_ms: start,
      end_ms: end,
    });
  const delegate = (id: string, offset_ms: number) =>
    emit({
      type: "session.delegation.created",
      delegation: { id, target: "client" },
      offset_ms,
    });
  const connect = async () => {
    await session.start();
    emit({ type: "session.started", session: { id: "voice-test" } });
  };
  return {
    session,
    transport,
    conversation,
    emit,
    transcript,
    delegate,
    connect,
  };
}

describe("ConversationVoiceSession", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("does not open a server session after connection cancellation", async () => {
    const { session, transport, conversation } = setup();
    let resolveOffer!: (offer: string) => void;
    transport.createOffer.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveOffer = resolve;
        }),
    );
    const starting = session.start();
    await session.start();
    session.stop();
    resolveOffer("late offer");
    await starting;
    expect(transport.createOffer).toHaveBeenCalledTimes(1);
    expect(conversation.createSession).not.toHaveBeenCalled();
    expect(transport.close).toHaveBeenCalledTimes(1);
  });

  it("aborts session creation and ignores a late answer after timeout", async () => {
    const { session, conversation, transport } = setup();
    let resolveAnswer!: (answer: string) => void;
    conversation.createSession.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveAnswer = resolve;
        }),
    );
    const starting = session.start();
    await vi.advanceTimersByTimeAsync(30_000);
    resolveAnswer("late answer");
    await starting;
    expect(conversation.onState).toHaveBeenLastCalledWith("error");
    expect(transport.acceptAnswer).not.toHaveBeenCalled();
  });

  it.each([
    [
      "createSession",
      new ApiRequestError(503, "private server details"),
      "service-error",
    ],
    [
      "createOffer",
      new DOMException("denied", "NotAllowedError"),
      "microphone-error",
    ],
    [
      "createOffer",
      new DOMException("missing", "NotFoundError"),
      "microphone-error",
    ],
    [
      "createOffer",
      new DOMException("busy", "NotReadableError"),
      "microphone-error",
    ],
    ["createOffer", new Error("connection failed"), "error"],
  ] as const)(
    "reports %s failures without exposing raw errors (%s)",
    async (operation, error, state) => {
      const { session, transport, conversation, connect } = setup();
      const attempt =
        operation === "createSession"
          ? conversation.createSession
          : transport.createOffer;
      attempt.mockRejectedValueOnce(error);
      await session.start();
      expect(conversation.onState).toHaveBeenLastCalledWith(state);
      expect(transport.close).toHaveBeenCalledOnce();
      expect(conversation.onEnded).toHaveBeenCalledWith({
        sessionId: null,
        seconds: null,
        finalized: false,
        failed: true,
      });
      session.stop();
      expect(transport.close).toHaveBeenCalledOnce();
      await connect();
      expect(conversation.onState).toHaveBeenLastCalledWith("connected");
    },
  );

  it.each([true, false])(
    "stops the microphone and releases the connection (finalized: %s)",
    async (finalized) => {
      const { session, transport, conversation, emit, connect } = setup();
      await connect();
      session.stop();
      expect(transport.mute).toHaveBeenCalledOnce();
      expect(transport.close).not.toHaveBeenCalled();
      expect(JSON.parse(transport.send.mock.calls[0][0])).toEqual({
        type: "session.close",
      });
      if (finalized) emit({ type: "session.closed", usage: { seconds: 12 } });
      else await vi.advanceTimersByTimeAsync(3000);
      expect(transport.close).toHaveBeenCalledOnce();
      expect(conversation.onEnded).toHaveBeenCalledWith({
        sessionId: "voice-test",
        seconds: finalized ? 12 : null,
        finalized,
        failed: false,
      });
      expect(conversation.sendMessage).not.toHaveBeenCalled();
    },
  );

  it("joins fragments once and keeps consecutive requests separate", async () => {
    const { connect, transcript, delegate, conversation } = setup();
    await connect();
    transcript("Find ", 0, 80);
    delegate("one", 100);
    transcript("the error", 80, 120);
    transcript("the error", 80, 120);
    delegate("one", 100);
    transcript("Fix it", 200, 250);
    delegate("two", 250);
    await vi.advanceTimersByTimeAsync(300);
    expect(conversation.sendMessage.mock.calls).toEqual([
      ["Spoken conversation:\nUser: Find the error"],
      ["Spoken conversation:\nUser: Fix it"],
    ]);
  });

  it("does not speak old history or partial replies, and speaks a final reply once", async () => {
    const { session, connect, transport } = setup();
    session.updateReply("Old answer", true, "old");
    await connect();
    session.updateReply("New", false, "streaming");
    expect(transport.send).not.toHaveBeenCalled();
    session.updateReply("New answer", true, "new");
    session.updateReply("New answer", true, "new");
    expect(transport.send).toHaveBeenCalledTimes(1);
    expect(JSON.parse(transport.send.mock.calls[0][0])).toEqual({
      type: "session.commentary.append",
      delegation_id: null,
      content: "New answer",
    });
    session.updateReply("New answer", true, "next-turn");
    expect(transport.send).toHaveBeenCalledTimes(2);
  });

  it("reports rejected requests with their own delegation IDs", async () => {
    const { connect, conversation, transcript, delegate, transport } = setup();
    await connect();
    conversation.sendMessage.mockResolvedValue(false);
    transcript("Do work", 0, 100);
    delegate("failed-request", 100);
    await vi.advanceTimersByTimeAsync(300);
    expect(JSON.parse(transport.send.mock.calls[0][0])).toMatchObject({
      delegation_id: "failed-request",
      content: expect.stringContaining("not sent"),
    });
  });

  it("keeps long non-Latin replies within the append token limit without losing text", () => {
    const answer = "结果🐱 ".repeat(1000);
    const chunks = voiceCommentaryChunks(answer);
    expect(chunks.join("")).toBe(answer);
    expect(
      chunks.every((chunk) => new TextEncoder().encode(chunk).length <= 480),
    ).toBe(true);
  });
});

import "reflect-metadata";
import {
  LIVE_VOICE_TRANSPORT,
  type LiveVoiceTransport,
} from "@posthog/platform/speech";
import { decorate, inject, injectable } from "inversify";
import { liveVoiceEventSchema, type VoiceState } from "./schemas";

export interface VoiceConversation {
  createSession(sdp: string, signal: AbortSignal): Promise<string>;
  sendMessage(text: string): Promise<boolean>;
  onState(state: VoiceState): void;
  onEnded(result: {
    sessionId: string | null;
    seconds: number | null;
    finalized: boolean;
    failed: boolean;
  }): void;
}

export const CONVERSATION_VOICE_SESSION = Symbol.for("posthog.voice.session");
export type VoiceSessionFactory = (
  conversation: VoiceConversation,
) => ConversationVoiceSession;
export const VOICE_SESSION_FACTORY = Symbol.for("posthog.voice.sessionFactory");
export const VOICE_CONVERSATION = Symbol.for("posthog.voice.conversation");

// UTF-8 bytes bound token count, including non-Latin text and emoji.
export function voiceCommentaryChunks(text: string): string[] {
  const chunks: string[] = [];
  let chunk = "";
  let bytes = 0;
  for (const char of text) {
    const code = char.codePointAt(0) ?? 0;
    const size = code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
    if (bytes + size > 480) {
      chunks.push(chunk);
      chunk = "";
      bytes = 0;
    }
    chunk += char;
    bytes += size;
  }
  if (chunk) chunks.push(chunk);
  return chunks;
}

export class ConversationVoiceSession {
  private state: VoiceState = "idle";
  private generation = 0;
  private readonly seen = new Set<string>();
  private transcripts: {
    role: string;
    text: string;
    start: number;
    end: number;
  }[] = [];
  private reply = "";
  private dispatch = Promise.resolve();
  private timeout: ReturnType<typeof setTimeout> | undefined;
  private readonly delegationTimers = new Set<ReturnType<typeof setTimeout>>();
  private abort: AbortController | undefined;
  private sessionId: string | null = null;
  private seconds: number | null = null;

  constructor(
    private readonly transport: LiveVoiceTransport,
    private readonly conversation: VoiceConversation,
  ) {}

  private setState(state: VoiceState): void {
    this.state = state;
    this.conversation.onState(state);
  }

  private append(content: string, delegationId: string | null = null): void {
    if (this.state !== "connected" || !content.trim()) return;
    for (const chunk of voiceCommentaryChunks(content)) {
      this.transport.send(
        JSON.stringify({
          type: "session.commentary.append",
          delegation_id: delegationId,
          content: chunk,
        }),
      );
    }
  }

  private delegate(id: string, offset: number, generation: number): void {
    if (generation !== this.generation || this.state !== "connected") return;
    const parts = this.transcripts
      .filter((part) => part.start <= offset)
      .sort((a, b) => a.start - b.start);
    this.transcripts = this.transcripts.filter((part) => part.start > offset);
    if (!parts.some((part) => part.role === "User" && part.text.trim())) {
      this.append("I did not receive your request. Please say it again.", id);
      return;
    }
    const turns: { role: string; text: string }[] = [];
    for (const part of parts) {
      const previous = turns.at(-1);
      if (previous?.role === part.role) previous.text += part.text;
      else turns.push({ role: part.role, text: part.text });
    }
    const text = turns.map((part) => `${part.role}: ${part.text}`).join("\n");
    this.dispatch = this.dispatch.then(async () => {
      if (generation !== this.generation || this.state !== "connected") return;
      let accepted = false;
      try {
        accepted = await this.conversation.sendMessage(
          `Spoken conversation:\n${text}`,
        );
      } catch {
        /* Report delivery failure through voice. */
      }
      if (generation !== this.generation) return;
      this.append(
        accepted
          ? "The request was sent to the task agent. Wait for its result before claiming that the work is complete."
          : "Your message was not sent. Please use the text box to try again.",
        id,
      );
    });
  }

  private receive(raw: string, generation: number): void {
    if (generation !== this.generation) return;
    let input: unknown;
    try {
      input = JSON.parse(raw);
    } catch {
      return;
    }
    const parsed = liveVoiceEventSchema.safeParse(input);
    if (!parsed.success) return;
    const event = parsed.data;
    if (event.type === "session.closed") {
      this.seconds = event.usage?.seconds ?? this.seconds;
      this.finish(false, true);
    } else if (event.type === "session.usage.updated") {
      this.seconds = event.usage.seconds;
    } else if (event.type === "error") {
      this.finish(true);
    } else if (this.state === "closing") {
      return;
    } else if (event.type === "session.started") {
      if (this.state !== "connecting") return;
      this.sessionId = event.session.id;
      this.setState("connected");
      clearTimeout(this.timeout);
      this.timeout = setTimeout(() => this.stop(), 5 * 60_000);
    } else if (event.type === "session.delegation.created") {
      const id = `delegation:${event.delegation.id}`;
      if (this.seen.has(id)) return;
      this.seen.add(id);
      // Transcript delivery can lag the delegation event.
      const timer = setTimeout(() => {
        this.delegationTimers.delete(timer);
        this.delegate(event.delegation.id, event.offset_ms, generation);
      }, 300);
      this.delegationTimers.add(timer);
    } else {
      if (this.seen.has(event.event_id)) return;
      this.seen.add(event.event_id);
      this.transcripts.push({
        role:
          event.type === "session.input_transcript.delta"
            ? "User"
            : "Voice assistant",
        text: event.delta,
        start: event.start_ms,
        end: event.end_ms,
      });
    }
  }

  async start(): Promise<void> {
    if (this.state !== "idle" && this.state !== "error") return;
    const generation = ++this.generation;
    this.seen.clear();
    this.transcripts = [];
    this.dispatch = Promise.resolve();
    this.sessionId = null;
    this.seconds = null;
    this.abort = new AbortController();
    this.setState("connecting");
    this.timeout = setTimeout(() => this.finish(true), 30_000);
    try {
      const offer = await this.transport.createOffer(
        (message) => this.receive(message, generation),
        () => {
          if (generation === this.generation) this.finish(true);
        },
      );
      if (generation !== this.generation) return;
      const answer = await this.conversation.createSession(
        offer,
        this.abort.signal,
      );
      if (generation !== this.generation) return;
      await this.transport.acceptAnswer(answer);
    } catch {
      if (generation === this.generation) this.finish(true);
    }
  }

  updateReply(text: string, complete: boolean, key = text): void {
    if (!complete || key === this.reply) return;
    this.reply = key;
    // Text and voice share a task. A final task reply can include either input.
    this.append(text);
  }

  stop(): void {
    if (
      this.state === "idle" ||
      this.state === "error" ||
      this.state === "closing"
    )
      return;
    if (this.state === "connecting") {
      this.finish(false);
      return;
    }
    this.setState("closing");
    this.transport.mute();
    clearTimeout(this.timeout);
    this.timeout = setTimeout(() => this.finish(false), 3_000);
    this.transport.send(JSON.stringify({ type: "session.close" }));
  }

  private finish(failed: boolean, finalized = false): void {
    if (this.state === "idle" || this.state === "error") return;
    ++this.generation;
    clearTimeout(this.timeout);
    for (const timer of this.delegationTimers) clearTimeout(timer);
    this.delegationTimers.clear();
    this.abort?.abort();
    this.transport.close();
    this.conversation.onEnded({
      sessionId: this.sessionId,
      seconds: this.seconds,
      finalized,
      failed,
    });
    this.setState(failed ? "error" : "idle");
  }
}

// Mobile's Metro compiler does not support parameter decorators.
decorate(injectable(), ConversationVoiceSession);
decorate(inject(LIVE_VOICE_TRANSPORT), ConversationVoiceSession, 0);
decorate(inject(VOICE_CONVERSATION), ConversationVoiceSession, 1);

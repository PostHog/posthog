import { RICH_OUTPUT_TAGS_PROMPT } from "@posthog/shared/rich-output-prompt";
import { inject, injectable, optional } from "inversify";
import type { AuthService, FetchLike } from "../auth/auth";
import { AUTH_SERVICE } from "../auth/auth.module";

export const QUICK_ASK_SERVICE = Symbol.for("posthog.core.quickAsk.service");
/**
 * Fetch implementation for quick-ask HTTP. Hosts may bind a transport that is
 * more reliable than Node's global fetch (the Electron main process binds
 * Chromium's `net.fetch`, which honors system proxies/VPNs undici trips over).
 */
export const QUICK_ASK_FETCH = Symbol.for("posthog.core.quickAsk.fetch");

/**
 * Events the quick-ask panel renders, distilled from a PostHog AI sandbox
 * run's SSE stream (the same task-run stream the web app's PostHog AI and the
 * desktop's cloud sessions consume). Text arrives as growing snapshots keyed
 * by a per-turn id; the renderer replaces by id.
 */
export type QuickAskEvent =
  | { type: "conversation"; conversationId: string }
  | { type: "reasoning"; content: string }
  | { type: "text"; id: string; content: string; complete: boolean }
  | { type: "error"; message: string; detail?: string }
  | { type: "done" }
  | { type: "trace"; detail: string };

export interface QuickAskInput {
  question: string;
  /** Continues an existing thread; omitted for the first question. */
  conversationId?: string;
}

/**
 * Steering for the sandbox agent, sent after the user's first question (so
 * the task title stays the question). `<posthog_trusted_context>` is the
 * sanctioned channel for app-injected guidance: the PostHog AI system prompt
 * instructs the agent to follow it like system instructions. The tag
 * vocabulary is the shared block the renderer's object-tag pipeline parses.
 */
const PANEL_STEERING = `<posthog_trusted_context>
This question was asked from PostHog Desktop's compact quick-ask panel, not a full chat. For this whole conversation:
- Answer from PostHog data using the PostHog MCP tools. Do not clone repositories or modify code.
- Keep the text answer short - a few sentences at most.
- Never ask a blocking question; make reasonable assumptions and state them briefly.
- Rich output: ${RICH_OUTPUT_TAGS_PROMPT}
</posthog_trusted_context>`;

/** One parsed SSE event: name, optional resume id, joined data lines. */
export interface SseFrame {
  event: string;
  id?: string;
  data: string;
}

/** Minimal SSE parser: collects `event:`/`id:`/`data:` lines per blank-line-delimited block. */
export function* parseSseChunk(buffer: string): Generator<SseFrame> {
  for (const block of buffer.split("\n\n")) {
    let event = "message";
    let id: string | undefined;
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("id:")) {
        id = line.slice(3).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      }
    }
    if (dataLines.length > 0) {
      yield { event, id, data: dataLines.join("\n") };
    }
  }
}

interface SessionUpdate {
  sessionUpdate?: string;
  content?: { type?: string; text?: string };
  title?: string;
  _meta?: { claudeCode?: { toolName?: string } };
}

interface NotificationFrame {
  type?: string;
  notification?: {
    method?: string;
    params?: {
      update?: SessionUpdate;
      message?: unknown;
      status?: string;
    };
  };
  status?: string;
  error_message?: string | null;
}

interface OpenResponse {
  task_id?: string;
  run_id?: string;
  run_status?: string;
}

/** Terminal run statuses on `task_run_state` frames. */
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

/**
 * Per-conversation state. The conversation id is minted client-side and keyed
 * to a products/tasks `(task, run)` by the sandbox `open` endpoint; `cursor`
 * is the Redis stream id of the last ingested event, carried across turns and
 * stream rotations so no frame is ever re-rendered or missed.
 */
interface QuickAskSession {
  conversationId: string;
  taskId: string | null;
  runId: string | null;
  cursor: string | null;
  /** The task has been filed into the user's personal channel. */
  filed: boolean;
  /** Number of questions sent (the first carries the steering block). */
  turns: number;
}

/**
 * What one stream frame means for the current turn. Split from the service so
 * the wire-format translation is testable without a live stream.
 */
export type TurnSignal =
  | { kind: "user-echo" }
  | { kind: "agent-text"; text: string }
  | { kind: "reasoning"; text: string }
  | { kind: "tool"; label: string }
  | { kind: "turn-complete" }
  | { kind: "run-terminal"; status: string; errorMessage?: string }
  | { kind: "ignore"; detail?: string };

export function translateFrame(parsed: unknown): TurnSignal {
  const frame = parsed as NotificationFrame;
  if (frame.type === "task_run_state") {
    const status = frame.status ?? "";
    if (TERMINAL_RUN_STATUSES.has(status)) {
      return {
        kind: "run-terminal",
        status,
        errorMessage: frame.error_message ?? undefined,
      };
    }
    return { kind: "ignore", detail: `run state ${status}` };
  }
  if (frame.type !== "notification" || !frame.notification) {
    return { kind: "ignore" };
  }
  const method = frame.notification.method ?? "";
  if (method === "_posthog/turn_complete") {
    return { kind: "turn-complete" };
  }
  if (method === "_posthog/error") {
    const message = frame.notification.params?.message;
    return {
      kind: "run-terminal",
      status: "failed",
      errorMessage: typeof message === "string" ? message : undefined,
    };
  }
  if (method !== "session/update") {
    return { kind: "ignore", detail: method || undefined };
  }
  const update = frame.notification.params?.update;
  switch (update?.sessionUpdate) {
    case "user_message_chunk":
      return { kind: "user-echo" };
    case "agent_message_chunk":
    case "agent_message":
      return update.content?.type === "text" && update.content.text
        ? { kind: "agent-text", text: update.content.text }
        : { kind: "ignore" };
    case "agent_thought_chunk":
      return update.content?.type === "text" && update.content.text
        ? { kind: "reasoning", text: update.content.text }
        : { kind: "ignore" };
    case "tool_call": {
      const label =
        update.title || update._meta?.claudeCode?.toolName || "a tool";
      return { kind: "tool", label };
    }
    default:
      return { kind: "ignore", detail: update?.sessionUpdate };
  }
}

/** Last non-empty line of the accumulated thought text - the live status label. */
export function reasoningLabel(thoughtBuffer: string): string {
  const lines = thoughtBuffer
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  return lines[lines.length - 1] ?? "";
}

/** Surfaces `error.cause` too: undici hides the real network error there. */
function describeError(error: unknown): string {
  if (!(error instanceof Error)) {
    return String(error);
  }
  const cause = error.cause instanceof Error ? ` (${error.cause.message})` : "";
  return `${error.message}${cause}`;
}

const OPEN_UNAVAILABLE_MESSAGE =
  "PostHog AI tasks are unavailable right now. Try again.";

/**
 * Streams PostHog AI answers for the quick-ask panel through the sandbox task
 * runtime: `open` warms/provisions a prewarmed sandbox run, each question is a
 * turn on that run, and the answer streams from the task-run SSE endpoint.
 * Business logic only - the host forwards events over IPC.
 */
@injectable()
export class QuickAskService {
  private controller: AbortController | null = null;
  private warmPromise: Promise<void> | null = null;
  private session: QuickAskSession | null = null;
  private readonly fetchImpl: FetchLike;

  constructor(
    @inject(AUTH_SERVICE)
    private readonly authService: AuthService,
    @inject(QUICK_ASK_FETCH) @optional() fetchImpl?: FetchLike,
  ) {
    this.fetchImpl = fetchImpl ?? fetch;
  }

  cancel(): void {
    this.controller?.abort();
    this.controller = null;
  }

  private async context(): Promise<{
    apiHost: string;
    projectId: number;
  } | null> {
    const { apiHost } = await this.authService.getValidAccessToken();
    const projectId = this.authService.getState().currentProjectId;
    return projectId == null ? null : { apiHost, projectId };
  }

  private ensureSession(conversationId?: string): QuickAskSession {
    if (
      this.session &&
      (!conversationId || this.session.conversationId === conversationId)
    ) {
      return this.session;
    }
    this.session = {
      conversationId: conversationId ?? globalThis.crypto.randomUUID(),
      taskId: null,
      runId: null,
      cursor: null,
      filed: false,
      turns: 0,
    };
    return this.session;
  }

  /** Drops the current thread so the next question starts a fresh task. */
  reset(): void {
    this.cancel();
    this.session = null;
  }

  private async postOpen(
    apiHost: string,
    projectId: number,
    conversationId: string,
    content: string | null,
    signal?: AbortSignal,
  ): Promise<Response> {
    return this.authService.authenticatedFetch(
      this.fetchImpl,
      `${apiHost}/api/environments/${projectId}/conversations/${conversationId}/open/`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          content == null
            ? {}
            : { content, trace_id: globalThis.crypto.randomUUID() },
        ),
        signal,
      },
    );
  }

  /**
   * Boots a sandbox ahead of the first question (called on panel summon), so
   * asking costs a model turn instead of a cold sandbox boot. Best-effort:
   * every failure is swallowed - a cold ask still works without it.
   */
  warm(): Promise<void> {
    if (this.warmPromise) return this.warmPromise;
    if (this.session?.runId) return Promise.resolve();
    this.warmPromise = (async () => {
      const context = await this.context();
      if (!context) return;
      const session = this.ensureSession();
      const response = await this.postOpen(
        context.apiHost,
        context.projectId,
        session.conversationId,
        null,
      );
      // 204 = warm pool full; anything non-ok is reported by the real ask.
      if (!response.ok || response.status === 204) return;
      const payload = (await response.json()) as OpenResponse;
      if (payload.task_id && payload.run_id) {
        session.taskId = payload.task_id;
        session.runId = payload.run_id;
      }
    })()
      .catch(() => undefined)
      .finally(() => {
        this.warmPromise = null;
      });
    return this.warmPromise;
  }

  /**
   * Files the conversation's task into the user's personal channel so the
   * thread shows up in their personal space (and can be continued as a full
   * desktop session). Best-effort: a failure never disturbs the answer.
   */
  private async fileTaskToPersonalChannel(
    apiHost: string,
    projectId: number,
    taskId: string,
  ): Promise<void> {
    const channelsResponse = await this.authService.authenticatedFetch(
      this.fetchImpl,
      `${apiHost}/api/projects/${projectId}/task_channels/`,
      { method: "GET" },
    );
    if (!channelsResponse.ok) {
      throw new Error(`task_channels failed with ${channelsResponse.status}`);
    }
    const channels = (await channelsResponse.json()) as {
      results?: { id?: string; channel_type?: string }[];
    };
    const list = Array.isArray(channels)
      ? (channels as { id?: string; channel_type?: string }[])
      : (channels.results ?? []);
    // The list is requester-scoped: the only personal channel is the user's own.
    const personal = list.find((entry) => entry.channel_type === "personal");
    if (!personal?.id) {
      throw new Error("no personal channel in task_channels response");
    }
    const patchResponse = await this.authService.authenticatedFetch(
      this.fetchImpl,
      `${apiHost}/api/projects/${projectId}/tasks/${taskId}/`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel: personal.id }),
      },
    );
    if (!patchResponse.ok) {
      throw new Error(`task channel patch failed with ${patchResponse.status}`);
    }
  }

  async *ask(input: QuickAskInput): AsyncGenerator<QuickAskEvent> {
    this.cancel();
    const controller = new AbortController();
    this.controller = controller;

    const context = await this.context();
    if (!context) {
      yield { type: "error", message: "Sign in to PostHog to ask questions." };
      return;
    }
    const { apiHost, projectId } = context;

    // Let an in-flight summon warm finish first so the ask reuses its run
    // instead of racing it for the conversation row.
    if (this.warmPromise) {
      await this.warmPromise;
    }
    const session = this.ensureSession(input.conversationId);
    yield { type: "conversation", conversationId: session.conversationId };

    const firstTurn = session.turns === 0;
    const content = firstTurn
      ? `${input.question}\n\n${PANEL_STEERING}`
      : input.question;

    let openResponse: Response;
    try {
      openResponse = await this.postOpen(
        apiHost,
        projectId,
        session.conversationId,
        content,
        controller.signal,
      );
    } catch (error) {
      yield {
        type: "error",
        message: OPEN_UNAVAILABLE_MESSAGE,
        detail: describeError(error),
      };
      return;
    }
    if (!openResponse.ok) {
      const detail = await openResponse
        .text()
        .then((text) => text.slice(0, 500))
        .catch(() => "");
      yield {
        type: "error",
        message:
          openResponse.status === 402
            ? "You are out of PostHog AI credits."
            : openResponse.status === 400
              ? "PostHog AI tasks are not enabled for this project."
              : `PostHog AI is unavailable right now (${openResponse.status}).`,
        detail,
      };
      return;
    }
    const opened = (await openResponse.json()) as OpenResponse;
    if (!opened.task_id || !opened.run_id) {
      yield {
        type: "error",
        message: OPEN_UNAVAILABLE_MESSAGE,
        detail: "open returned no task/run handle",
      };
      return;
    }
    // A resume after a terminal run mints a successor run; reset the cursor
    // so the new run's stream is read from its beginning.
    if (session.runId !== opened.run_id) {
      session.cursor = null;
    }
    session.taskId = opened.task_id;
    session.runId = opened.run_id;
    session.turns += 1;

    if (!session.filed) {
      session.filed = true;
      void this.fileTaskToPersonalChannel(
        apiHost,
        projectId,
        opened.task_id,
      ).catch(() => {
        // Filing is cosmetic; the conversation itself is unaffected.
      });
    }

    yield* this.streamTurn(apiHost, projectId, session, controller);
  }

  /**
   * Reads the run's SSE stream from the session cursor until the turn
   * completes. `event: end` (server-side connection rotation) reconnects with
   * the cursor; `event: stream-end` means the run itself finished.
   */
  private async *streamTurn(
    apiHost: string,
    projectId: number,
    session: QuickAskSession,
    controller: AbortController,
  ): AsyncGenerator<QuickAskEvent> {
    const turnId = `turn-${session.turns}`;
    let answerText = "";
    let thoughtBuffer = "";
    let toolSinceText = false;
    // Frames before this turn's own user-message echo are a previous turn's
    // tail (or warm boot noise) - skip them. A brand-new stream (no cursor)
    // also opens the gate on the first agent activity, in case the harness
    // does not echo the first message.
    let gateOpen = false;
    const freshStream = session.cursor == null;

    const finish = (): QuickAskEvent[] =>
      answerText
        ? [
            { type: "text", id: turnId, content: answerText, complete: true },
            { type: "done" },
          ]
        : [{ type: "done" }];

    try {
      let rotations = 0;
      while (true) {
        const response = await this.authService.authenticatedFetch(
          this.fetchImpl,
          `${apiHost}/api/projects/${projectId}/tasks/${session.taskId}/runs/${session.runId}/stream/`,
          {
            method: "GET",
            headers: {
              Accept: "text/event-stream",
              ...(session.cursor
                ? { "Last-Event-ID": session.cursor }
                : undefined),
            },
            signal: controller.signal,
          },
        );
        if (!response.ok || !response.body) {
          yield {
            type: "error",
            message: OPEN_UNAVAILABLE_MESSAGE,
            detail: `stream failed with ${response.status}`,
          };
          return;
        }

        let rotated = false;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        const frames = async function* (): AsyncGenerator<SseFrame> {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            // Process complete SSE blocks; keep the trailing partial block.
            const lastDelimiter = buffer.lastIndexOf("\n\n");
            if (lastDelimiter === -1) continue;
            const complete = buffer.slice(0, lastDelimiter);
            buffer = buffer.slice(lastDelimiter + 2);
            yield* parseSseChunk(complete);
          }
          yield* parseSseChunk(buffer);
        };

        for await (const frame of frames()) {
          if (frame.id) {
            session.cursor = frame.id;
          }
          if (frame.event === "end") {
            rotated = true; // Server rotates long connections; resume below.
            break;
          }
          if (frame.event === "stream-end") {
            yield* finish();
            return;
          }
          if (frame.event === "error") {
            yield {
              type: "error",
              message: OPEN_UNAVAILABLE_MESSAGE,
              detail: frame.data.slice(0, 500),
            };
            return;
          }
          if (frame.event !== "message") {
            continue; // keepalive and other named events carry nothing to fold.
          }
          let parsed: unknown;
          try {
            parsed = JSON.parse(frame.data);
          } catch {
            continue;
          }
          const signal = translateFrame(parsed);
          switch (signal.kind) {
            case "user-echo":
              gateOpen = true;
              break;
            case "agent-text":
              if (!gateOpen && !freshStream) break;
              gateOpen = true;
              if (toolSinceText && answerText) {
                answerText += "\n\n";
              }
              toolSinceText = false;
              answerText += signal.text;
              yield {
                type: "text",
                id: turnId,
                content: answerText,
                complete: false,
              };
              break;
            case "reasoning": {
              if (!gateOpen && !freshStream) break;
              gateOpen = true;
              thoughtBuffer += signal.text;
              const label = reasoningLabel(thoughtBuffer);
              if (label) {
                yield { type: "reasoning", content: label };
              }
              break;
            }
            case "tool":
              if (!gateOpen && !freshStream) break;
              gateOpen = true;
              toolSinceText = true;
              yield { type: "reasoning", content: `Running ${signal.label}…` };
              break;
            case "turn-complete":
              if (!gateOpen) break; // A previous turn's boundary.
              yield* finish();
              return;
            case "run-terminal":
              // The sandbox ended (timeout, failure, cancellation). The next
              // question resumes into a successor run via `open`.
              session.runId = null;
              session.cursor = null;
              if (signal.status === "failed") {
                yield {
                  type: "error",
                  message: "PostHog AI hit an error. Try asking again.",
                  detail: signal.errorMessage,
                };
              } else {
                yield* finish();
              }
              return;
            case "ignore":
              if (signal.detail) {
                yield {
                  type: "trace",
                  detail: `stream frame ignored (${signal.detail})`,
                };
              }
              break;
          }
        }

        if (!rotated) {
          // Clean EOF without the stream-end sentinel: connection dropped.
          rotations += 1;
          if (rotations > 20) {
            yield {
              type: "error",
              message: OPEN_UNAVAILABLE_MESSAGE,
              detail: "stream kept dropping",
            };
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, 500));
          if (controller.signal.aborted) return;
        }
      }
    } finally {
      if (this.controller === controller) {
        this.controller = null;
      }
    }
  }
}

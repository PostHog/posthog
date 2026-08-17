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
 * Events the quick-ask panel renders, distilled from the task run's SSE
 * stream. Text arrives as growing snapshots keyed by a per-turn id; the
 * renderer replaces by id.
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
 * Sent after the user's first question, so the task title stays the question.
 * The tag vocabulary is the shared block the renderer's object-tag pipeline
 * parses.
 */
export const PANEL_STEERING = `<posthog_trusted_context>
This question was asked from PostHog Desktop's compact quick-ask panel. For this whole conversation:
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
      prompt?: { type?: string; text?: string }[];
    };
  };
  status?: string;
  error_message?: string | null;
}

interface TaskResponse {
  id?: string;
  latest_run?: { id?: string; status?: string } | null;
}

interface RunResponse {
  id?: string;
}

interface WarmHandle {
  taskId: string;
  runId: string;
}

/** Terminal run statuses on `task_run_state` frames. */
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

/**
 * Per-thread state. `conversationId` is a client-minted key the renderer
 * echoes back so follow-ups land on the same task; `cursor` is the stream id
 * of the last ingested event, carried across turns and reconnects so no frame
 * is re-rendered or missed.
 */
interface QuickAskSession {
  conversationId: string;
  taskId: string | null;
  runId: string | null;
  cursor: string | null;
  /** Number of questions sent (the first carries the steering block). */
  turns: number;
}

/** What one stream frame means for the current turn. */
export type TurnSignal =
  | { kind: "prompt"; text: string }
  | { kind: "agent-text"; text: string }
  | { kind: "reasoning"; text: string }
  | { kind: "tool"; label: string }
  | { kind: "turn-complete" }
  | { kind: "run-terminal"; status: string; errorMessage?: string }
  | { kind: "ignore"; detail?: string };

export function translateFrame(parsed: unknown): TurnSignal {
  const frame = parsed as NotificationFrame;
  if (frame.type === "permission_request") {
    return { kind: "reasoning", text: "Waiting for a tool approval…" };
  }
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
  // The harness logs every prompt as a `session/prompt` request; the run can
  // carry prompts besides ours (the workflow prompts the task description at
  // boot), so the caller matches the text to find its own turn.
  if (method === "session/prompt") {
    const text = (frame.notification.params?.prompt ?? [])
      .map((block) => block.text ?? "")
      .join("");
    return { kind: "prompt", text };
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

/** Last non-empty line of the accumulated thought text, shown as the live status label. */
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

const UNAVAILABLE_MESSAGE =
  "PostHog AI tasks are unavailable right now. Try again.";

/**
 * Streams quick-ask answers through prewarmed cloud task runs: summoning the
 * panel warms a repo-less sandbox, each question is a turn on the thread's
 * run, and the answer streams from the run's SSE endpoint. Business logic
 * only; the host forwards events over IPC.
 */
@injectable()
export class QuickAskService {
  private controller: AbortController | null = null;
  private warmPromise: Promise<void> | null = null;
  private warmHandle: WarmHandle | null = null;
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
      turns: 0,
    };
    return this.session;
  }

  /** Drops the current thread so the next question starts a fresh task. */
  reset(): void {
    this.cancel();
    this.session = null;
  }

  private post(
    apiHost: string,
    path: string,
    body: unknown,
    signal?: AbortSignal,
  ): Promise<Response> {
    return this.authService.authenticatedFetch(
      this.fetchImpl,
      `${apiHost}${path}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      },
    );
  }

  /**
   * Boots a repo-less sandbox on panel summon, so the first ask starts at
   * model speed. Best-effort: failures are swallowed and a cold ask still
   * works.
   */
  warm(): Promise<void> {
    if (this.warmPromise) return this.warmPromise;
    if (this.session?.runId) return Promise.resolve();
    this.warmPromise = (async () => {
      const context = await this.context();
      if (!context) return;
      const response = await this.post(
        context.apiHost,
        `/api/projects/${context.projectId}/tasks/warm/`,
        {
          repository: null,
          repositories: [],
          github_integration: null,
          branch: null,
        },
      );
      if (!response.ok) return;
      // An empty body means warming is off or the pool is full.
      const text = await response.text().catch(() => "");
      if (!text) return;
      const handle = JSON.parse(text) as { task_id?: string; run_id?: string };
      if (handle.task_id && handle.run_id) {
        this.warmHandle = { taskId: handle.task_id, runId: handle.run_id };
      }
    })()
      .catch(() => undefined)
      .finally(() => {
        this.warmPromise = null;
      });
    return this.warmPromise;
  }

  /**
   * Creates the thread's task. `branch` must be present (null) to trigger the
   * backend's warm-run lookup: a matching idle sandbox is activated with the
   * pending message; otherwise the task returns runless and the caller starts
   * a run. Repo-less user-created tasks file into the personal channel.
   */
  private async createTask(
    apiHost: string,
    projectId: number,
    question: string,
    content: string,
    signal: AbortSignal,
  ): Promise<Response> {
    return this.post(
      apiHost,
      `/api/projects/${projectId}/tasks/`,
      {
        description: question,
        repositories: [],
        branch: null,
        pending_user_message: content,
      },
      signal,
    );
  }

  /** Creates and starts an interactive cloud run carrying the message. */
  private async startRun(
    apiHost: string,
    projectId: number,
    taskId: string,
    content: string,
    signal: AbortSignal,
  ): Promise<string | null> {
    const createResponse = await this.post(
      apiHost,
      `/api/projects/${projectId}/tasks/${taskId}/runs/`,
      {
        environment: "cloud",
        mode: "interactive",
        runtime_adapter: "claude",
        // "auto" lets the agent use safe tools without approval prompts the
        // panel has no surface for.
        initial_permission_mode: "auto",
      },
      signal,
    );
    if (!createResponse.ok) return null;
    const run = (await createResponse.json()) as RunResponse;
    if (!run.id) return null;
    const startResponse = await this.post(
      apiHost,
      `/api/projects/${projectId}/tasks/${taskId}/runs/${run.id}/start/`,
      { pending_user_message: content },
      signal,
    );
    return startResponse.ok ? run.id : null;
  }

  /**
   * Warm runs boot in the "default" permission mode, which holds every tool
   * call for an approval the panel has no surface for; switch the agent to
   * "auto" before the first message reaches it. Best-effort.
   */
  private async setAutoMode(
    apiHost: string,
    projectId: number,
    handle: WarmHandle,
    signal: AbortSignal,
  ): Promise<void> {
    await this.post(
      apiHost,
      `/api/projects/${projectId}/tasks/${handle.taskId}/runs/${handle.runId}/command/`,
      {
        jsonrpc: "2.0",
        id: globalThis.crypto.randomUUID(),
        method: "set_config_option",
        params: { configId: "mode", value: "auto" },
      },
      signal,
    ).catch(() => undefined);
  }

  /** Signals a follow-up question onto the live run. */
  private async sendUserMessage(
    apiHost: string,
    projectId: number,
    taskId: string,
    runId: string,
    content: string,
    signal: AbortSignal,
  ): Promise<boolean> {
    const response = await this.post(
      apiHost,
      `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/command/`,
      {
        jsonrpc: "2.0",
        id: globalThis.crypto.randomUUID(),
        method: "user_message",
        params: { content },
      },
      signal,
    );
    return response.ok;
  }

  /** Route one question onto the session's task, minting runs as needed. */
  private async placeTurn(
    apiHost: string,
    projectId: number,
    session: QuickAskSession,
    question: string,
    content: string,
    signal: AbortSignal,
  ): Promise<{ ok: true } | { ok: false; status: number; detail: string }> {
    // A run that died since the last turn rejects the command; fall through
    // to a successor run.
    if (session.taskId && session.runId) {
      const sent = await this.sendUserMessage(
        apiHost,
        projectId,
        session.taskId,
        session.runId,
        content,
        signal,
      );
      if (sent) return { ok: true };
      session.runId = null;
      session.cursor = null;
    }

    if (session.taskId) {
      const runId = await this.startRun(
        apiHost,
        projectId,
        session.taskId,
        content,
        signal,
      );
      if (!runId) {
        return { ok: false, status: 0, detail: "starting a run failed" };
      }
      session.runId = runId;
      session.cursor = null;
      return { ok: true };
    }

    if (this.warmHandle) {
      await this.setAutoMode(apiHost, projectId, this.warmHandle, signal);
      this.warmHandle = null;
    }
    const response = await this.createTask(
      apiHost,
      projectId,
      question,
      content,
      signal,
    );
    if (!response.ok) {
      const detail = await response
        .text()
        .then((text) => text.slice(0, 500))
        .catch(() => "");
      return { ok: false, status: response.status, detail };
    }
    const task = (await response.json()) as TaskResponse;
    if (!task.id) {
      return { ok: false, status: 0, detail: "task creation returned no id" };
    }
    session.taskId = task.id;
    if (task.latest_run?.id) {
      session.runId = task.latest_run.id;
      session.cursor = null;
      return { ok: true };
    }
    const runId = await this.startRun(
      apiHost,
      projectId,
      task.id,
      content,
      signal,
    );
    if (!runId) {
      return { ok: false, status: 0, detail: "starting a run failed" };
    }
    session.runId = runId;
    session.cursor = null;
    return { ok: true };
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

    // The create call must see the idling sandbox, not race its provisioning.
    if (this.warmPromise) {
      await this.warmPromise;
    }
    const session = this.ensureSession(input.conversationId);
    yield { type: "conversation", conversationId: session.conversationId };

    const firstTurn = session.turns === 0;
    const content = firstTurn
      ? `${input.question}\n\n${PANEL_STEERING}`
      : input.question;

    let placed: Awaited<ReturnType<typeof this.placeTurn>>;
    try {
      placed = await this.placeTurn(
        apiHost,
        projectId,
        session,
        input.question,
        content,
        controller.signal,
      );
    } catch (error) {
      yield {
        type: "error",
        message: UNAVAILABLE_MESSAGE,
        detail: describeError(error),
      };
      return;
    }
    if (!placed.ok) {
      yield {
        type: "error",
        message:
          placed.status === 402 || placed.status === 429
            ? "Your organization is out of PostHog task credits."
            : placed.status === 403
              ? "Your account can't run PostHog tasks in this project."
              : `PostHog AI is unavailable right now (${placed.status || "no run"}).`,
        detail: placed.detail,
      };
      return;
    }
    session.turns += 1;

    yield* this.streamTurn(apiHost, projectId, session, content, controller);
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
    content: string,
    controller: AbortController,
  ): AsyncGenerator<QuickAskEvent> {
    const turnId = `turn-${session.turns}`;
    let answerText = "";
    let thoughtBuffer = "";
    let toolSinceText = false;
    // The run can carry prompts besides ours (the workflow prompts the task
    // description at boot), and prompt queueing logs a prompt when queued, so
    // ordering alone cannot attribute frames. Find our prompt by text, count
    // the prompts still unanswered ahead of it, and take only the output
    // between their completions and ours. A stream with no logged prompts
    // falls back to treating all agent activity as ours.
    const target = content.trim();
    let promptsBefore = 0;
    let completionsBefore = 0;
    let matched = false;
    let turnsAhead = 0;
    let completionsAfter = 0;
    const freshStream = session.cursor == null;
    const inOurTurn = (): boolean =>
      matched
        ? completionsAfter === turnsAhead
        : freshStream && promptsBefore === 0;

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
            message: UNAVAILABLE_MESSAGE,
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
              message: UNAVAILABLE_MESSAGE,
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
            case "prompt":
              if (matched) break; // Queued behind ours; not our concern.
              if (signal.text.trim() === target) {
                matched = true;
                turnsAhead = Math.max(0, promptsBefore - completionsBefore);
              } else {
                promptsBefore += 1;
              }
              break;
            case "agent-text":
              if (!inOurTurn()) break;
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
              if (!inOurTurn()) break;
              thoughtBuffer += signal.text;
              const label = reasoningLabel(thoughtBuffer);
              if (label) {
                yield { type: "reasoning", content: label };
              }
              break;
            }
            case "tool":
              if (!inOurTurn()) break;
              toolSinceText = true;
              yield { type: "reasoning", content: `Running ${signal.label}…` };
              break;
            case "turn-complete":
              if (matched) {
                completionsAfter += 1;
                if (completionsAfter > turnsAhead) {
                  yield* finish();
                  return;
                }
                break;
              }
              if (freshStream && promptsBefore === 0) {
                yield* finish();
                return;
              }
              completionsBefore += 1;
              break;
            case "run-terminal":
              // The sandbox ended; the next question starts a successor run.
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
              message: UNAVAILABLE_MESSAGE,
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

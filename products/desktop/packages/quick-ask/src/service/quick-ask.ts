import type { AuthService, FetchLike } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import { inject, injectable, optional } from "inversify";
import { PANEL_STEERING } from "./steering";

export const QUICK_ASK_SERVICE = Symbol.for("posthog.core.quickAsk.service");
/**
 * Fetch implementation for quick-ask HTTP. Hosts may bind a transport that is
 * more reliable than Node's global fetch (the Electron main process binds
 * Chromium's `net.fetch`, which honors system proxies/VPNs undici trips over).
 */
export const QUICK_ASK_FETCH = Symbol.for("posthog.core.quickAsk.fetch");

/** Where new quick-ask threads run: the space they file into and the repos
 * their sandbox clones. Empty values mean the personal space and no repos. */
export interface QuickAskRunDefaults {
  channelId: string | null;
  repositories: string[];
  githubIntegrationId: number | null;
  adapter: string | null;
  model: string | null;
  reasoningEffort: string | null;
}

export const QUICK_ASK_RUN_DEFAULTS = Symbol.for(
  "posthog.core.quickAsk.runDefaults",
);

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
  | { type: "done" };

export interface QuickAskInput {
  question: string;
  /** Continues an existing thread; omitted for the first question. */
  conversationId?: string;
  /** Annotated screenshots to attach to this message. */
  attachments?: QuickAskAttachment[];
}

export interface QuickAskAttachment {
  name: string;
  base64: string;
  mimeType: string;
}

export { PANEL_STEERING } from "./steering";

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

interface PrepareUploadResponse {
  artifacts?: {
    id: string;
    presigned_post: { url: string; fields: Record<string, string> };
  }[];
}

/** Terminal run statuses on `task_run_state` frames. */
const TERMINAL_RUN_STATUSES = new Set(["completed", "failed", "cancelled"]);

/**
 * Consecutive stream connection failures tolerated without any frame
 * arriving. Long-lived SSE connections drop routinely (proxies reset HTTP/2
 * streams), so drops reconnect from the cursor; progress resets the budget.
 */
const MAX_STREAM_ATTEMPTS = 8;

function reconnectDelay(attempts: number): Promise<void> {
  return new Promise((resolve) =>
    setTimeout(resolve, Math.min(500 * attempts, 5000)),
  );
}

/**
 * Deadline for the non-stream task calls and attachment uploads. Passing the
 * turn signal to AuthService replaces its own default deadline, so a stalled
 * proxy or half-open socket would otherwise wedge the panel in "Thinking…"
 * with no error. The SSE stream is deliberately left unbounded.
 */
const REQUEST_TIMEOUT_MS = 30_000;

/**
 * Bounds a request by both the turn signal and a timeout, so cancelling the
 * turn or a stall each abort it. Used for every non-stream call; the SSE fetch
 * keeps the raw turn signal.
 */
function withRequestTimeout(signal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(REQUEST_TIMEOUT_MS);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

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
  | { kind: "agent-text"; text: string; final: boolean }
  | { kind: "reasoning"; text: string }
  | { kind: "tool"; label: string }
  | { kind: "status"; text: string }
  | { kind: "turn-complete" }
  | { kind: "run-terminal"; status: string; errorMessage?: string }
  | { kind: "ignore"; detail?: string };

export function translateFrame(parsed: unknown): TurnSignal {
  const frame = parsed as NotificationFrame;
  if (frame.type === "permission_request") {
    return { kind: "status", text: "Waiting for a tool approval…" };
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
  if (method === "session/request_permission") {
    return { kind: "status", text: "Waiting for a tool approval…" };
  }
  if (method === "_posthog/progress") {
    const params = frame.notification.params as
      | { label?: unknown; status?: unknown }
      | undefined;
    return typeof params?.label === "string" && params.status !== "completed"
      ? { kind: "status", text: params.label }
      : { kind: "ignore" };
  }
  if (method !== "session/update") {
    return { kind: "ignore", detail: method || undefined };
  }
  const update = frame.notification.params?.update;
  switch (update?.sessionUpdate) {
    case "agent_message_chunk":
    case "agent_message":
      // `agent_message_chunk` frames are deltas; the `agent_message` that
      // closes them carries the complete snapshot, so the consumer must
      // replace rather than append (else the answer text lands twice).
      return update.content?.type === "text" && update.content.text
        ? {
            kind: "agent-text",
            text: update.content.text,
            final: update.sessionUpdate === "agent_message",
          }
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
    @inject(QUICK_ASK_RUN_DEFAULTS)
    @optional()
    private readonly runDefaults?: () => QuickAskRunDefaults,
  ) {
    this.fetchImpl = fetchImpl ?? fetch;
  }

  private defaults(): QuickAskRunDefaults {
    return (
      this.runDefaults?.() ?? {
        channelId: null,
        repositories: [],
        githubIntegrationId: null,
        adapter: null,
        model: null,
        reasoningEffort: null,
      }
    );
  }

  cancel(): void {
    this.controller?.abort();
    this.controller = null;
  }

  /** Task backing the current thread, for opening it in the app. */
  get currentTaskId(): string | null {
    return this.session?.taskId ?? null;
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
        signal: withRequestTimeout(signal),
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
      const defaults = this.defaults();
      const response = await this.post(
        context.apiHost,
        `/api/projects/${context.projectId}/tasks/warm/`,
        {
          repository: defaults.repositories[0] ?? null,
          repositories: defaults.repositories,
          github_integration: defaults.githubIntegrationId,
          branch: null,
          runtime_adapter: defaults.adapter,
          model: defaults.model,
          reasoning_effort: defaults.reasoningEffort,
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
   * Creates the thread's task. The backend's warm-run lookup triggers only
   * when `branch` is present (null): a matching idle sandbox is activated
   * with the pending message. `reuseWarm: false` omits the key entirely, so
   * the task returns runless and the caller starts a cold run — the safe
   * route when the warm run couldn't be prepared for this message. Repo-less
   * user-created tasks file into the personal channel.
   */
  private async createTask(
    apiHost: string,
    projectId: number,
    question: string,
    content: string,
    pendingArtifactIds: string[],
    reuseWarm: boolean,
    signal: AbortSignal,
  ): Promise<Response> {
    const defaults = this.defaults();
    return this.post(
      apiHost,
      `/api/projects/${projectId}/tasks/`,
      {
        description: question,
        ...(reuseWarm ? { branch: null } : {}),
        pending_user_message: content,
        pending_user_artifact_ids: pendingArtifactIds,
        ...(defaults.channelId ? { channel: defaults.channelId } : {}),
        // Explicit repos win; a space brings its own; otherwise none. Omitting
        // the key lets the space's repositories apply server-side.
        ...(defaults.repositories.length
          ? {
              repositories: defaults.repositories,
              github_integration: defaults.githubIntegrationId,
            }
          : defaults.channelId
            ? {}
            : { repositories: [] }),
        ...(defaults.adapter ? { runtime_adapter: defaults.adapter } : {}),
        ...(defaults.model ? { model: defaults.model } : {}),
        ...(defaults.reasoningEffort
          ? { reasoning_effort: defaults.reasoningEffort }
          : {}),
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
    artifactIds: string[],
    signal: AbortSignal,
  ): Promise<string | null> {
    const defaults = this.defaults();
    const createResponse = await this.post(
      apiHost,
      `/api/projects/${projectId}/tasks/${taskId}/runs/`,
      {
        environment: "cloud",
        mode: "interactive",
        runtime_adapter: defaults.adapter ?? "claude",
        ...(defaults.model ? { model: defaults.model } : {}),
        ...(defaults.reasoningEffort
          ? { reasoning_effort: defaults.reasoningEffort }
          : {}),
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
      {
        pending_user_message: content,
        pending_user_artifact_ids: artifactIds,
      },
      signal,
    );
    return startResponse.ok ? run.id : null;
  }

  /**
   * Warm runs boot in the "default" permission mode, which holds every tool
   * call for an approval the panel has no surface for; switch the agent to
   * "auto" before the first message reaches it. Returns whether the switch
   * landed — a warm run left in default mode must not receive the question,
   * or the turn parks forever on an approval prompt the panel can't answer.
   */
  private async setAutoMode(
    apiHost: string,
    projectId: number,
    handle: WarmHandle,
    signal: AbortSignal,
  ): Promise<boolean> {
    try {
      const response = await this.post(
        apiHost,
        `/api/projects/${projectId}/tasks/${handle.taskId}/runs/${handle.runId}/command/`,
        {
          jsonrpc: "2.0",
          id: globalThis.crypto.randomUUID(),
          method: "set_config_option",
          params: { configId: "mode", value: "auto" },
        },
        signal,
      );
      return response.ok;
    } catch {
      return false;
    }
  }

  /** Signals a follow-up question onto the live run. */
  private async sendUserMessage(
    apiHost: string,
    projectId: number,
    taskId: string,
    runId: string,
    content: string,
    artifactIds: string[],
    signal: AbortSignal,
  ): Promise<boolean> {
    const response = await this.post(
      apiHost,
      `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/command/`,
      {
        jsonrpc: "2.0",
        id: globalThis.crypto.randomUUID(),
        method: "user_message",
        params: artifactIds.length
          ? { content, artifact_ids: artifactIds }
          : { content },
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
    attachments: QuickAskAttachment[],
    signal: AbortSignal,
  ): Promise<{ ok: true } | { ok: false; status: number; detail: string }> {
    // A run that died since the last turn rejects the command; fall through
    // to a successor run.
    if (session.taskId && session.runId) {
      const artifactIds = await this.uploadAttachments(
        apiHost,
        projectId,
        `tasks/${session.taskId}/runs/${session.runId}/artifacts`,
        attachments,
        signal,
      );
      if (artifactIds) {
        const sent = await this.sendUserMessage(
          apiHost,
          projectId,
          session.taskId,
          session.runId,
          content,
          artifactIds,
          signal,
        );
        if (sent) return { ok: true };
      }
      session.runId = null;
      session.cursor = null;
    }

    if (session.taskId) {
      const runId = await this.startStagedRun(
        apiHost,
        projectId,
        session.taskId,
        content,
        attachments,
        signal,
      );
      if (!runId) {
        return { ok: false, status: 0, detail: "starting a run failed" };
      }
      session.runId = runId;
      session.cursor = null;
      return { ok: true };
    }

    let warmArtifactIds: string[] = [];
    // Reusing a warm run forwards the pending message as-is, so it is only
    // safe when any attachments are already uploaded to that run. When the
    // upload fails — or attachments exist with no warm run to carry them —
    // the task is created without the warm lookup, and the cold staged path
    // below re-uploads them (or fails the turn); riding a warm run anyway
    // would silently answer without the screenshots.
    let reuseWarm = attachments.length === 0;
    if (this.warmHandle) {
      const handle = this.warmHandle;
      this.warmHandle = null;
      // A warm run stuck in default mode would park the question on an
      // approval the panel can't answer; decline the reuse and go cold (the
      // cold run sets auto mode server-side in its create body).
      const autoReady = await this.setAutoMode(
        apiHost,
        projectId,
        handle,
        signal,
      );
      if (!autoReady) {
        reuseWarm = false;
      }
      if (autoReady && attachments.length > 0) {
        const uploaded = await this.uploadAttachments(
          apiHost,
          projectId,
          `tasks/${handle.taskId}/runs/${handle.runId}/artifacts`,
          attachments,
          signal,
        );
        if (uploaded) {
          warmArtifactIds = uploaded;
          reuseWarm = true;
        }
      }
    }
    const response = await this.createTask(
      apiHost,
      projectId,
      question,
      content,
      warmArtifactIds,
      reuseWarm,
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
    const runId = await this.startStagedRun(
      apiHost,
      projectId,
      task.id,
      content,
      attachments,
      signal,
    );
    if (!runId) {
      return { ok: false, status: 0, detail: "starting a run failed" };
    }
    session.runId = runId;
    session.cursor = null;
    return { ok: true };
  }

  /**
   * Uploads attachments through the tasks artifact store: prepare presigned
   * S3 posts, upload the bytes, finalize. `basePath` picks run artifacts
   * (live/warm run) or staged task artifacts (cold start). Returns the
   * artifact ids, or null when any step fails.
   */
  private async uploadAttachments(
    apiHost: string,
    projectId: number,
    basePath: string,
    attachments: QuickAskAttachment[],
    signal: AbortSignal,
  ): Promise<string[] | null> {
    if (!attachments.length) return [];
    const files = attachments.map((attachment) => ({
      bytes: Uint8Array.from(atob(attachment.base64), (c) => c.charCodeAt(0)),
      name: attachment.name,
      mimeType: attachment.mimeType,
    }));
    const prefix = `/api/projects/${projectId}/${basePath}`;
    const prepareResponse = await this.post(
      apiHost,
      `${prefix}/prepare_upload/`,
      {
        artifacts: files.map((file) => ({
          name: file.name,
          type: "user_attachment",
          source: "posthog_code",
          size: file.bytes.byteLength,
          content_type: file.mimeType,
        })),
      },
      signal,
    );
    if (!prepareResponse.ok) return null;
    const prepared = ((await prepareResponse.json()) as PrepareUploadResponse)
      .artifacts;
    if (!prepared || prepared.length !== files.length) return null;
    for (const [index, artifact] of prepared.entries()) {
      const file = files[index];
      const form = new FormData();
      for (const [key, value] of Object.entries(
        artifact.presigned_post.fields,
      )) {
        form.append(key, value);
      }
      form.append(
        "file",
        new Blob([file.bytes], { type: file.mimeType }),
        file.name,
      );
      const uploadResponse = await this.fetchImpl(artifact.presigned_post.url, {
        method: "POST",
        body: form,
        signal: withRequestTimeout(signal),
      });
      if (!uploadResponse.ok) return null;
    }
    const finalizeResponse = await this.post(
      apiHost,
      `${prefix}/finalize_upload/`,
      { artifacts: prepared },
      signal,
    );
    if (!finalizeResponse.ok) return null;
    const finalized = ((await finalizeResponse.json()) as PrepareUploadResponse)
      .artifacts;
    if (!finalized || finalized.length !== files.length) return null;
    return finalized.map((artifact) => artifact.id);
  }

  /** Stages attachments on the task, then creates and starts a cold run. */
  private async startStagedRun(
    apiHost: string,
    projectId: number,
    taskId: string,
    content: string,
    attachments: QuickAskAttachment[],
    signal: AbortSignal,
  ): Promise<string | null> {
    const artifactIds = await this.uploadAttachments(
      apiHost,
      projectId,
      `tasks/${taskId}/staged_artifacts`,
      attachments,
      signal,
    );
    if (!artifactIds) return null;
    return this.startRun(
      apiHost,
      projectId,
      taskId,
      content,
      artifactIds,
      signal,
    );
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
        input.attachments ?? [],
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
    // Text between stretches of tool activity forms its own segment; the
    // panel pages through them.
    let segment = 0;
    let segmentText = "";
    const segmentId = (): string =>
      segment === 0 ? turnId : `${turnId}.${segment + 1}`;
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
      segmentText
        ? [
            {
              type: "text",
              id: segmentId(),
              content: segmentText,
              complete: true,
            },
            { type: "done" },
          ]
        : [{ type: "done" }];

    try {
      let attempts = 0;
      while (true) {
        let response: Response;
        try {
          response = await this.authService.authenticatedFetch(
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
        } catch (error) {
          if (controller.signal.aborted) return;
          attempts += 1;
          if (attempts > MAX_STREAM_ATTEMPTS) {
            yield {
              type: "error",
              message: UNAVAILABLE_MESSAGE,
              detail: describeError(error),
            };
            return;
          }
          await reconnectDelay(attempts);
          if (controller.signal.aborted) return;
          continue;
        }
        if (!response.ok || !response.body) {
          attempts += 1;
          if (attempts > MAX_STREAM_ATTEMPTS) {
            yield {
              type: "error",
              message: UNAVAILABLE_MESSAGE,
              detail: `stream failed with ${response.status}`,
            };
            return;
          }
          await reconnectDelay(attempts);
          if (controller.signal.aborted) return;
          continue;
        }

        let rotated = false;
        let dropped = false;
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

        try {
          for await (const frame of frames()) {
            if (frame.id) {
              session.cursor = frame.id;
              attempts = 0; // Progress restores the reconnect budget.
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
                if (toolSinceText && segmentText) {
                  yield {
                    type: "text",
                    id: segmentId(),
                    content: segmentText,
                    complete: true,
                  };
                  segment += 1;
                  segmentText = "";
                }
                toolSinceText = false;
                // A closing `agent_message` supersedes the chunks it followed;
                // replace so the snapshot does not double its own text.
                segmentText = signal.final
                  ? signal.text
                  : segmentText + signal.text;
                yield {
                  type: "text",
                  id: segmentId(),
                  content: segmentText,
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
                yield {
                  type: "reasoning",
                  content: `Running ${signal.label}…`,
                };
                break;
              case "status":
                yield { type: "reasoning", content: signal.text };
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
                break;
            }
          }
        } catch (error) {
          // A mid-read network failure (proxies reset long HTTP/2 streams);
          // reconnect from the cursor like a rotation.
          if (controller.signal.aborted) return;
          dropped = true;
          attempts += 1;
          if (attempts > MAX_STREAM_ATTEMPTS) {
            yield {
              type: "error",
              message: UNAVAILABLE_MESSAGE,
              detail: describeError(error),
            };
            return;
          }
        } finally {
          // Release this connection on every exit — terminal return, rotation,
          // or retry — so the server is not left holding an idle SSE stream
          // (and its Redis reader) until its 900s cap. cancel() closes the
          // socket; an already-errored reader rejects, so swallow that.
          await reader.cancel().catch(() => {});
        }

        if (rotated) continue;
        if (!dropped) {
          // Clean EOF without the stream-end sentinel: connection dropped.
          attempts += 1;
          if (attempts > MAX_STREAM_ATTEMPTS) {
            yield {
              type: "error",
              message: UNAVAILABLE_MESSAGE,
              detail: "stream kept dropping",
            };
            return;
          }
        }
        await reconnectDelay(attempts);
        if (controller.signal.aborted) return;
      }
    } finally {
      // The turn is over; abort so the fetch/socket is torn down even if a
      // reader cancel did not fully propagate, and so this turn's controller
      // cannot linger past it.
      controller.abort();
      if (this.controller === controller) {
        this.controller = null;
      }
    }
  }
}

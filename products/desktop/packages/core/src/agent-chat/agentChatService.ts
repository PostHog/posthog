import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type {
  AgentSessionEvent,
  DecideApprovalRequest,
} from "@posthog/shared/agent-platform-types";
import { injectable } from "inversify";
import { agentChatStore } from "./agentChatStore";
import type {
  AgentChatMapper,
  AgentChatSession,
  ClientToolCallData,
} from "./identifiers";

/** Session states with no further activity to tail — render stored history only. */
const TERMINAL_SESSION_STATES = new Set([
  "completed",
  "closed",
  "cancelled",
  "failed",
]);

/**
 * The request id when `text` is the runner's rejection wake envelope
 * (`{"approval":{"state":"rejected",…}}`), else null. A reject lands as a
 * `user_message` (no tool_call_id), so this is how the live stream clears the
 * inline card for a session decided elsewhere (e.g. Slack).
 */
function rejectedApprovalRequestId(text: string | undefined): string | null {
  if (!text) return null;
  try {
    const parsed = JSON.parse(text) as {
      approval?: { request_id?: string; state?: string };
    };
    if (
      parsed.approval?.state === "rejected" &&
      typeof parsed.approval.request_id === "string"
    ) {
      return parsed.approval.request_id;
    }
  } catch {
    // Not JSON / not an approval envelope — a normal user message.
  }
  return null;
}

/**
 * Bounded reconnect budget for a dropped `/listen` tail. A re-attach that yields
 * any event resets the budget, so a healthy long run that keeps getting closed
 * out (idle timeouts, proxy recycling) reconnects indefinitely; only a genuinely
 * dead or vanished stream exhausts it and surfaces an error.
 */
const MAX_LISTEN_RECONNECTS = 6;

/** Reserve a margin so we mint a fresh token before the server rejects the old one. */
const PREVIEW_TOKEN_EARLY_REFRESH_MS = 30_000;

/** Exponential backoff (capped at 8s) between `/listen` reconnect attempts. */
function reconnectBackoffMs(attempt: number): number {
  return Math.min(500 * 2 ** (attempt - 1), 8_000);
}

/** Resolve after `ms`, or early (→ false) if `signal` aborts; else → true. */
function delay(ms: number, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false);
  return new Promise((resolve) => {
    const onAbort = () => {
      clearTimeout(timer);
      resolve(false);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve(true);
    }, ms);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * The ingress signals an expired/missing preview token with the fetcher's
 * `Failed request: [401] …` shape, same as any other auth failure. Anything
 * else falls through to the caller as a normal error.
 */
function isPreviewAuthError(err: unknown): boolean {
  return err instanceof Error && /\[401\]/.test(err.message);
}

interface CachedPreviewToken {
  token: string;
  expiresAtMs: number;
}

/** Per-chat saga state — one live `/listen` loop, mapper, and token cache. */
interface ChatRuntime {
  mapper: AgentChatMapper;
  abort: AbortController | null;
  streaming: boolean;
  /** Each stream attach bumps this; a superseded loop checks it before touching the store. */
  epoch: number;
  previewToken: CachedPreviewToken | null;
  revisionId: string | null;
}

/**
 * Drives live chats against deployed agents' ingress: starts/sends/cancels via
 * the api-client, streams SSE through the host's mapper, and pumps the resulting
 * ACP messages into the core `agentChatStore` keyed by `chatId` (so the agent
 * builder dock and per-agent chats coexist). One `ChatRuntime` per chat holds
 * the reconnect loop, epoch supersede, and preview-token cache.
 *
 * The renderer hook supplies the authenticated client per call and the UI seams
 * (mapper, client-tool resolution, context envelope, history) via the session.
 */
@injectable()
export class AgentChatService {
  private readonly runtimes = new Map<string, ChatRuntime>();

  /** Ensure a runtime exists, dropping a cached token when the revision changes. */
  private runtime(session: AgentChatSession): ChatRuntime {
    let rt = this.runtimes.get(session.chatId);
    if (!rt) {
      rt = {
        mapper: session.createMapper(),
        abort: null,
        streaming: false,
        epoch: 0,
        previewToken: null,
        revisionId: session.revisionId,
      };
      this.runtimes.set(session.chatId, rt);
    }
    // A token is bound to a specific (app, revision); a stale one wouldn't route
    // to the new target when the consumer flips revisions (incl. live ↔ draft).
    if (rt.revisionId !== session.revisionId) {
      rt.revisionId = session.revisionId;
      rt.previewToken = null;
    }
    return rt;
  }

  /**
   * Mint a preview token if we don't have one, or refresh it just before expiry.
   * `force` skips the cache (post-401 retry). Returns null for live revisions.
   */
  private async getPreviewToken(
    client: PostHogAPIClient,
    rt: ChatRuntime,
    session: AgentChatSession,
    force = false,
  ): Promise<string | null> {
    if (!session.revisionId) return null;
    const cached = rt.previewToken;
    if (
      !force &&
      cached &&
      cached.expiresAtMs - Date.now() > PREVIEW_TOKEN_EARLY_REFRESH_MS
    ) {
      return cached.token;
    }
    const minted = await client.mintAgentPreviewToken(
      session.agentSlug,
      session.revisionId,
    );
    rt.previewToken = {
      token: minted.token,
      // Backend returns TTL in seconds; store an absolute deadline so the
      // early-refresh comparison is straight subtraction.
      expiresAtMs: Date.now() + minted.expires_in * 1000,
    };
    return minted.token;
  }

  /**
   * Run an ingress call with the cached preview token; on the fetcher's `[401]`,
   * mint fresh and retry once. For live revisions this is just `call(null)`.
   */
  private async withPreviewToken<T>(
    client: PostHogAPIClient,
    rt: ChatRuntime,
    session: AgentChatSession,
    call: (token: string | null) => Promise<T>,
  ): Promise<T> {
    const token = await this.getPreviewToken(client, rt, session);
    try {
      return await call(token);
    } catch (err) {
      if (!session.revisionId || !isPreviewAuthError(err)) throw err;
      const fresh = await this.getPreviewToken(client, rt, session, true);
      return call(fresh);
    }
  }

  private async dispatchClientTool(
    client: PostHogAPIClient,
    rt: ChatRuntime,
    session: AgentChatSession,
    data: ClientToolCallData,
    sessionId: string,
  ): Promise<void> {
    const outcome = await session.resolveClientTool(data);
    // Interactive tools (set_secret) post their own outcome later.
    if (!outcome || outcome.defer) return;
    try {
      await this.withPreviewToken(client, rt, session, (token) =>
        client.sendAgentClientToolResult(
          session.ingressBaseUrl,
          sessionId,
          data.call_id,
          outcome,
          token,
        ),
      );
    } catch {
      // Best-effort — the session will time the call out if this fails.
    }
  }

  private async runStream(
    client: PostHogAPIClient,
    session: AgentChatSession,
    sessionId: string,
  ): Promise<void> {
    const { chatId } = session;
    const rt = this.runtime(session);
    // Supersede any in-flight stream (resume / new chat) and claim this epoch.
    rt.abort?.abort();
    const epoch = ++rt.epoch;
    const controller = new AbortController();
    rt.abort = controller;
    rt.streaming = true;
    const store = agentChatStore.getState();
    // True the moment a (re)attached stream yields a real event, so the
    // reconnect loop can tell "still producing output" from "attached to a
    // silent or ended session". Reset before every pump attempt.
    let madeProgress = false;
    // Last non-auth stream error, surfaced only if reconnects are exhausted.
    let lastDropError: string | null = null;
    // Pump the SSE generator with the supplied token. Returns:
    //   "remint"       — server signalled `preview_token_required`; mint + reconnect.
    //   "auth_failure" — initial fetch 401'd; safety-net retry once.
    //   "done"         — the stream ended (terminal frame, drop, or supersede).
    const pump = async (
      token: string | null,
    ): Promise<"remint" | "auth_failure" | "done"> => {
      try {
        for await (const event of client.streamAgentSession(
          session.ingressBaseUrl,
          sessionId,
          controller.signal,
          token,
        )) {
          if (rt.epoch !== epoch) return "done";
          // Control event: don't surface to the user, just request a remint.
          if (event.kind === "preview_token_required") return "remint";
          // Hard end (meta-end-session): the session is sealed and rejects
          // further `/send`s. Unlike `completed` (turn-end, stays open), this is
          // terminal — finalize and stop tailing. The mapper renders nothing for
          // it, so skip the append like the remint.
          if (event.kind === "closed") {
            store.setStatus(chatId, "completed");
            return "done";
          }
          madeProgress = true;
          store.appendMessages(chatId, rt.mapper.apply(event));
          this.trackApprovalState(client, rt, session, chatId, epoch, event);
          if (event.kind === "client_tool_call") {
            void this.dispatchClientTool(
              client,
              rt,
              session,
              event.data,
              sessionId,
            );
          } else if (event.kind === "completed") {
            store.setStatus(chatId, "completed");
          } else if (event.kind === "waiting") {
            store.setStatus(chatId, "awaiting_input");
          } else if (event.kind === "failed") {
            store.setStatus(chatId, "failed");
            store.setError(
              chatId,
              event.data?.reason ?? "The agent run failed.",
            );
          }
        }
        return "done";
      } catch (err) {
        if (
          session.revisionId &&
          !controller.signal.aborted &&
          isPreviewAuthError(err)
        ) {
          return "auth_failure";
        }
        // Network reset / idle-timeout close / parse failure: remember it but
        // don't surface yet — the loop reconnects, and only errors if the
        // session is gone or the reconnect budget is exhausted.
        if (!controller.signal.aborted) {
          lastDropError = err instanceof Error ? err.message : null;
        }
        return "done";
      }
    };
    // Is the run still live? `/listen` can't replay a terminal frame missed
    // during a gap, so on a silent re-attach we ask the api before retrying.
    const sessionLiveState = async (): Promise<
      "live" | "terminal" | "unknown"
    > => {
      try {
        const detail = await client.getAgentSessionViaIngress(
          session.ingressBaseUrl,
          sessionId,
          undefined,
          await this.getPreviewToken(client, rt, session),
        );
        return !detail || TERMINAL_SESSION_STATES.has(detail.state)
          ? "terminal"
          : "live";
      } catch {
        return "unknown";
      }
    };
    try {
      let token = await this.getPreviewToken(client, rt, session);
      // `preview_token_required` is unbounded (one re-mint per ~15 min TTL); a
      // true `[401]` only gets one retry as a safety net for the initial fetch.
      let authRetried = false;
      let reconnectAttempts = 0;
      while (true) {
        madeProgress = false;
        const outcome = await pump(token);
        if (rt.epoch !== epoch || controller.signal.aborted) break;
        if (outcome === "remint") {
          token = await this.getPreviewToken(client, rt, session, true);
          continue;
        }
        if (outcome === "auth_failure" && !authRetried) {
          authRetried = true;
          token = await this.getPreviewToken(client, rt, session, true);
          continue;
        }
        if (outcome === "auth_failure") {
          store.setError(
            chatId,
            "Preview session failed to authenticate. Try again.",
          );
          break;
        }
        // outcome === "done": a terminal/`waiting` frame already moved us off
        // "streaming" — that's an expected end, so stop.
        if (agentChatStore.getState().chats[chatId]?.status !== "streaming") {
          break;
        }
        // Still "streaming" → the connection dropped while the run is live.
        if (madeProgress) {
          // The re-attach produced output: reset the budget so repeated idle
          // drops never exhaust it.
          reconnectAttempts = 0;
        } else {
          // Silence on (re)attach: confirm the run didn't just finish in the gap
          // before spending the budget.
          const liveState = await sessionLiveState();
          if (rt.epoch !== epoch || controller.signal.aborted) break;
          if (liveState === "terminal") {
            store.setStatus(chatId, "completed");
            break;
          }
        }
        if (reconnectAttempts >= MAX_LISTEN_RECONNECTS) {
          store.setError(
            chatId,
            lastDropError ??
              "Lost connection to the agent. Send a message to retry.",
          );
          break;
        }
        reconnectAttempts += 1;
        const waited = await delay(
          reconnectBackoffMs(reconnectAttempts),
          controller.signal,
        );
        if (!waited || rt.epoch !== epoch || controller.signal.aborted) break;
        // Refresh a preview token that may have lapsed across the gap.
        token = await this.getPreviewToken(client, rt, session);
      }
    } catch (err) {
      // A `getPreviewToken` throw (mint or re-mint) lands here — `pump` handles
      // its own errors. Without this the rejection would slip past `finally`
      // (which only flips status) and the stream would quietly stop.
      if (rt.epoch === epoch && !controller.signal.aborted) {
        store.setError(
          chatId,
          err instanceof Error ? err.message : "Preview session unavailable.",
        );
      }
    } finally {
      // The loop has fully broken (terminal frame, exhausted budget, or
      // supersede), so release the still-open `/listen` socket: the server tails
      // perpetually and only tears down on client disconnect. `controller` is
      // run-local; re-aborting an aborted one is a no-op.
      controller.abort();
      if (rt.epoch === epoch) {
        rt.streaming = false;
        // Stream ended without a terminal frame mid-conversation → treat as
        // awaiting input so the composer stays usable.
        if (agentChatStore.getState().chats[chatId]?.status === "streaming") {
          agentChatStore.getState().setStatus(chatId, "awaiting_input");
        }
      }
    }
  }

  async start(
    client: PostHogAPIClient,
    session: AgentChatSession,
    text: string,
  ): Promise<void> {
    const rt = this.runtime(session);
    rt.mapper = session.createMapper();
    const s = agentChatStore.getState();
    s.begin(session.chatId, session.agentSlug);
    // Render the user's clean message immediately; the stream's echo (which
    // includes the context envelope) is stripped + deduped by the mapper.
    s.appendMessages(session.chatId, rt.mapper.seedUserMessage(text));
    try {
      const { session_id } = await this.withPreviewToken(
        client,
        rt,
        session,
        (token) =>
          client.runAgentSession(
            session.ingressBaseUrl,
            session.buildWireText(text),
            token,
            session.supportedClientTools,
          ),
      );
      agentChatStore.getState().setSessionId(session.chatId, session_id);
      agentChatStore.getState().setStatus(session.chatId, "streaming");
      session.onSessionStarted?.(session_id, text);
      void this.runStream(client, session, session_id);
    } catch (err) {
      agentChatStore.getState().setStatus(session.chatId, "failed");
      agentChatStore
        .getState()
        .setError(
          session.chatId,
          err instanceof Error ? err.message : "Couldn't start chat.",
        );
    }
  }

  async send(
    client: PostHogAPIClient,
    session: AgentChatSession,
    text: string,
  ): Promise<void> {
    const s = agentChatStore.getState();
    const sessionId = s.chats[session.chatId]?.sessionId;
    if (!sessionId) return this.start(client, session, text);
    const rt = this.runtime(session);
    // Render the user's message immediately; the stream's echo is deduped.
    s.appendMessages(session.chatId, rt.mapper.seedUserMessage(text));
    s.setStatus(session.chatId, "streaming");
    try {
      await this.withPreviewToken(client, rt, session, (token) =>
        client.sendAgentMessage(session.ingressBaseUrl, sessionId, text, token),
      );
      if (!rt.streaming) void this.runStream(client, session, sessionId);
    } catch (err) {
      s.setStatus(session.chatId, "failed");
      s.setError(
        session.chatId,
        err instanceof Error ? err.message : "Couldn't send.",
      );
    }
  }

  async cancel(
    client: PostHogAPIClient,
    session: AgentChatSession,
  ): Promise<void> {
    const s = agentChatStore.getState();
    const sessionId = s.chats[session.chatId]?.sessionId;
    const rt = this.runtime(session);
    rt.abort?.abort();
    s.setStatus(session.chatId, "cancelled");
    if (sessionId && session.ingressBaseUrl) {
      try {
        await this.withPreviewToken(client, rt, session, (token) =>
          client.cancelAgentSession(session.ingressBaseUrl, sessionId, token),
        );
      } catch {
        // Best-effort.
      }
    }
  }

  /**
   * Keep `chat.pendingApproval` in sync with the stream — what drives the inline
   * approval card, with no polling. A `queued` approval marker triggers a
   * one-shot fetch of the full request from the ingress (principal-authed,
   * cross-project, with the draft preview token when present); a non-queued
   * marker for that request, or a rejection wake, clears it.
   */
  private trackApprovalState(
    client: PostHogAPIClient,
    rt: ChatRuntime,
    session: AgentChatSession,
    chatId: string,
    epoch: number,
    event: AgentSessionEvent,
  ): void {
    if (event.kind === "tool_result" && event.data.approval) {
      const { request_id, state } = event.data.approval;
      if (state !== "queued") {
        this.clearPendingApprovalIf(chatId, request_id);
        return;
      }
      void (async () => {
        try {
          const token = await this.getPreviewToken(client, rt, session);
          const detail = await client.getAgentApprovalViaIngress(
            session.ingressBaseUrl,
            request_id,
            token,
          );
          // Skip if the stream was superseded (epoch) or the approval was
          // already decided while the fetch was in flight (re-checked state).
          if (detail && detail.state === "queued" && rt.epoch === epoch) {
            agentChatStore.getState().setPendingApproval(chatId, detail);
          }
        } catch {
          // Best-effort: the card just won't show; a reattach or a later marker
          // retries. Never let a detail fetch break the stream.
        }
      })();
      return;
    }
    if (event.kind === "user_message") {
      const rejectedId = rejectedApprovalRequestId(event.data.text);
      if (rejectedId) this.clearPendingApprovalIf(chatId, rejectedId);
    }
  }

  /** Clear the chat's pending approval only when it's the named request. */
  private clearPendingApprovalIf(chatId: string, requestId: string): void {
    const cur = agentChatStore.getState().chats[chatId]?.pendingApproval;
    if (cur?.id === requestId) {
      agentChatStore.getState().setPendingApproval(chatId, null);
    }
  }

  /**
   * Decide a `principal`-type tool approval for this chat's session at the
   * ingress, carrying the session's preview token so the ingress can
   * principal-match. On approve the runner wakes, dispatches the tool, and the
   * open `/listen` stream resumes the chat naturally — same as `/send`.
   */
  async decideApproval(
    client: PostHogAPIClient,
    session: AgentChatSession,
    approvalId: string,
    body: DecideApprovalRequest,
  ): Promise<void> {
    const rt = this.runtime(session);
    await this.withPreviewToken(client, rt, session, (token) =>
      client.decideAgentApprovalViaIngress(
        session.ingressBaseUrl,
        approvalId,
        body,
        token,
      ),
    );
    // Clear the inline card now — the stream's resolved marker clears it too,
    // but the approve→dispatch (or reject→wake) can lag, so don't leave the user
    // staring at a card they've already decided.
    agentChatStore.getState().setPendingApproval(session.chatId, null);
  }

  /**
   * Resolve an interactive client tool (set_secret) once the user submits its
   * form: post the outcome via `/send` (waking the parked session) and make sure
   * the stream is attached to receive the resulting turn.
   */
  async resolveInteractiveTool(
    client: PostHogAPIClient,
    session: AgentChatSession,
    callId: string,
    outcome: { result: Record<string, unknown> } | { error: string },
  ): Promise<void> {
    const sessionId =
      agentChatStore.getState().chats[session.chatId]?.sessionId;
    if (!sessionId) return;
    const rt = this.runtime(session);
    agentChatStore.getState().setStatus(session.chatId, "streaming");
    try {
      await this.withPreviewToken(client, rt, session, (token) =>
        client.sendAgentInteractiveToolResult(
          session.ingressBaseUrl,
          sessionId,
          callId,
          outcome,
          token,
        ),
      );
      if (!rt.streaming) void this.runStream(client, session, sessionId);
    } catch (err) {
      agentChatStore.getState().setStatus(session.chatId, "awaiting_input");
      agentChatStore
        .getState()
        .setError(
          session.chatId,
          err instanceof Error ? err.message : "Couldn't submit the secret.",
        );
    }
  }

  /**
   * Re-open a past chat. `/listen` only tails (it does not replay), so history is
   * rebuilt from the stored transcript; a still-active session then attaches the
   * live stream so the user can keep chatting where they left off.
   */
  async resume(
    client: PostHogAPIClient,
    session: AgentChatSession,
    sessionId: string,
  ): Promise<void> {
    if (
      agentChatStore.getState().chats[session.chatId]?.sessionId === sessionId
    )
      return;
    const rt = this.runtime(session);
    rt.abort?.abort();
    rt.epoch += 1;
    rt.streaming = false;
    rt.mapper = session.createMapper();
    const s = agentChatStore.getState();
    s.begin(session.chatId, session.agentSlug);
    s.setSessionId(session.chatId, sessionId);
    s.setStatus(session.chatId, "starting");
    try {
      const detail = await client.getAgentSessionViaIngress(
        session.ingressBaseUrl,
        sessionId,
        undefined,
        await this.getPreviewToken(client, rt, session),
      );
      // A newer resume/new-chat won the race while we were fetching.
      if (
        agentChatStore.getState().chats[session.chatId]?.sessionId !== sessionId
      )
        return;
      const conversation = detail?.conversation ?? [];
      agentChatStore
        .getState()
        .appendMessages(session.chatId, session.mapConversation(conversation));
      rt.mapper.setPromptIdBase(
        conversation.filter((m) => m.role === "user").length,
      );
      if (!detail || TERMINAL_SESSION_STATES.has(detail.state)) {
        agentChatStore.getState().setStatus(session.chatId, "completed");
      } else {
        agentChatStore.getState().setStatus(session.chatId, "streaming");
        void this.runStream(client, session, sessionId);
      }
    } catch (err) {
      if (
        agentChatStore.getState().chats[session.chatId]?.sessionId !== sessionId
      )
        return;
      agentChatStore.getState().setStatus(session.chatId, "failed");
      agentChatStore
        .getState()
        .setError(
          session.chatId,
          err instanceof Error ? err.message : "Couldn't load this chat.",
        );
    }
  }

  /** Clear the surface for a brand-new chat; the next send starts a new session. */
  newChat(session: AgentChatSession): void {
    const rt = this.runtime(session);
    rt.abort?.abort();
    rt.epoch += 1;
    rt.streaming = false;
    rt.mapper = session.createMapper();
    agentChatStore.getState().reset(session.chatId);
  }

  /** Release the open `/listen` socket when the consumer unmounts. */
  releaseStream(chatId: string): void {
    this.runtimes.get(chatId)?.abort?.abort();
  }
}

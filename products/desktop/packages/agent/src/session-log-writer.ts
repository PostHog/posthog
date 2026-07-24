import fs from "node:fs";
import fsp from "node:fs/promises";
import path from "node:path";
import { serializeError } from "@posthog/shared";
import type { PostHogAPIClient } from "./posthog-api";
import type { StoredNotification } from "./types";
import { isEmptyContentBlock } from "./utils/acp-content";
import { Logger } from "./utils/logger";

/**
 * Session context for a registered session.
 * These are set once per session and shared by every persisted entry.
 */
export interface SessionContext {
  /** Parent task grouping - all runs for a task share this */
  taskId: string;
  /** Primary conversation identifier - all events in a run share this */
  runId: string;
  /** Deployment environment - "local" for desktop, "cloud" for cloud sandbox */
  deviceType?: "local" | "cloud";
}

/**
 * Receives every parsed non-chunk notification the writer persists, in
 * arrival order. Streamed agent message/thought chunks are not delivered
 * (neither raw nor coalesced) - sinks carry run metadata, not transcript
 * content. Sink failures are swallowed so they can never break session log
 * persistence.
 */
export interface SessionLogSink {
  append(sessionId: string, entry: StoredNotification): void;
}

export interface SessionLogWriterOptions {
  /** PostHog API client for log persistence */
  posthogAPI?: PostHogAPIClient;
  /** Logger instance */
  logger?: Logger;
  /** Local cache path for instant log loading (e.g., ~/.posthog-code) */
  localCachePath?: string;
  /** Additional consumers of persisted entries (e.g. OTel telemetry) */
  sinks?: SessionLogSink[];
}

interface ChunkBuffer {
  text: string;
  firstTimestamp: string;
}

/**
 * In-progress `tool_call_update`s buffered per toolCallId, awaiting a
 * coalesced write to the local cache (see appendRawLine). `mergedUpdate` is
 * the shallow union of every buffered update (later fields win) — updates
 * carry different fields at different times (streamed rawInput snapshots,
 * input-derived title/content, terminal status/rawOutput), so writing only
 * the newest one would permanently drop the rest from the local file.
 * `latestEntry` supplies the envelope (timestamp etc.) for the merged write.
 * The merged update is a copy; entries shared with the API path are never
 * mutated.
 */
interface BufferedToolUpdate {
  latestEntry: StoredNotification;
  mergedUpdate: Record<string, unknown>;
  bufferedAt: number;
}

interface SessionState {
  context: SessionContext;
  chunkBuffer?: ChunkBuffer;
  lastAgentMessage?: string;
  currentTurnMessages: string[];
  toolUpdateCache: Map<string, BufferedToolUpdate>;
  pendingRawInputSnapshots: Map<string, StoredNotification>;
}

export class SessionLogWriter {
  /**
   * When consecutive in-progress tool updates for one call span more than this
   * window, the buffered union is written and a new window starts, so the
   * local cache keeps periodic snapshots during active streaming instead of only
   * the final one. Not a durability bound: the local file is a load cache, and
   * the API log keeps every update except intermediate rawInput-only streaming
   * snapshots (see queueForApiLog). A buffered union is otherwise written on a
   * terminal update, any non-tool event, or flushAll.
   */
  private static readonly TOOL_UPDATE_MAX_HOLD_MS = 2000;
  private static readonly FLUSH_DEBOUNCE_MS = 500;
  private static readonly FLUSH_MAX_INTERVAL_MS = 5000;
  private static readonly MAX_FLUSH_RETRIES = 10;
  private static readonly MAX_RETRY_DELAY_MS = 30_000;
  private static readonly SESSIONS_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;

  private posthogAPI?: PostHogAPIClient;
  private pendingEntries: Map<string, StoredNotification[]> = new Map();
  private flushTimeouts: Map<string, NodeJS.Timeout> = new Map();
  private lastFlushAttemptTime: Map<string, number> = new Map();
  private retryCounts: Map<string, number> = new Map();
  private sessions: Map<string, SessionState> = new Map();
  private flushQueues: Map<string, Promise<void>> = new Map();
  private sinks: SessionLogSink[];
  private warnedSinks: Set<SessionLogSink> = new Set();

  private logger: Logger;
  private localCachePath?: string;

  constructor(options: SessionLogWriterOptions = {}) {
    this.posthogAPI = options.posthogAPI;
    this.localCachePath = options.localCachePath;
    this.sinks = options.sinks ?? [];
    this.logger =
      options.logger ??
      new Logger({ debug: false, prefix: "[SessionLogWriter]" });
  }

  async flushAll(): Promise<void> {
    // Coalesce any in-progress chunk buffers before the final flush
    // During normal operation, chunks are coalesced when the next non-chunk
    // event arrives, but on shutdown there may be no subsequent event
    const flushPromises: Promise<void>[] = [];
    for (const [sessionId, session] of this.sessions) {
      this.emitCoalescedMessage(sessionId, session);
      this.flushToolUpdateCache(sessionId, session);
      this.drainRawInputSnapshots(sessionId, session);
      flushPromises.push(this.flush(sessionId));
    }
    await Promise.all(flushPromises);
  }

  register(sessionId: string, context: SessionContext): void {
    if (this.sessions.has(sessionId)) {
      return;
    }

    this.sessions.set(sessionId, {
      context,
      currentTurnMessages: [],
      toolUpdateCache: new Map(),
      pendingRawInputSnapshots: new Map(),
    });

    this.lastFlushAttemptTime.set(sessionId, Date.now());

    if (this.localCachePath) {
      const sessionDir = path.join(
        this.localCachePath,
        "sessions",
        context.runId,
      );
      try {
        fs.mkdirSync(sessionDir, { recursive: true });
      } catch (error) {
        this.logger.warn("Failed to create local cache directory", {
          sessionDir,
          error,
        });
      }
    }
  }

  isRegistered(sessionId: string): boolean {
    return this.sessions.has(sessionId);
  }

  appendRawLine(sessionId: string, line: string): void {
    const session = this.sessions.get(sessionId);
    if (!session) {
      this.logger.warn("appendRawLine called for unregistered session", {
        sessionId,
      });
      return;
    }

    try {
      const message = JSON.parse(line);
      const timestamp = new Date().toISOString();

      // Persisted empty thought chunks poison session resume: they rebuild
      // into empty text blocks the API rejects with a 400.
      if (this.isEmptyThoughtChunk(message)) {
        return;
      }

      // Check if this is an agent_message_chunk event
      if (this.isAgentMessageChunk(message)) {
        const text = this.extractChunkText(message);
        if (text) {
          if (!session.chunkBuffer) {
            session.chunkBuffer = { text, firstTimestamp: timestamp };
          } else {
            session.chunkBuffer.text += text;
          }
        }
        // Don't emit chunk events
        return;
      }

      // Non-chunk event: flush any buffered chunks first.
      // If this is a direct agent_message AND there are buffered chunks,
      // the direct message supersedes the partial chunks
      if (this.isDirectAgentMessage(message) && session.chunkBuffer) {
        session.chunkBuffer = undefined;
      } else {
        this.emitCoalescedMessage(sessionId, session);
      }

      const nonChunkAgentText = this.extractAgentMessageText(message);
      if (nonChunkAgentText) {
        session.lastAgentMessage = nonChunkAgentText;
        session.currentTurnMessages.push(nonChunkAgentText);
      }

      const entry: StoredNotification = {
        type: "notification",
        timestamp,
        notification: message,
      };

      this.emitToSinks(sessionId, entry);

      // Coalesce the local cache: buffer in-progress tool_call_update
      // snapshots (they re-send the full growing output) and write one merged
      // update per toolCallId. Written on a terminal update, any non-tool
      // event, or — during a long run of updates — once the hold window is
      // exceeded. The API path coalesces separately in queueForApiLog.
      const tcu = this.toolCallUpdateInfo(message);
      if (tcu && !tcu.terminal) {
        const cache = session.toolUpdateCache;
        const existing = cache.get(tcu.toolCallId);
        if (
          existing &&
          Date.now() - existing.bufferedAt >
            SessionLogWriter.TOOL_UPDATE_MAX_HOLD_MS
        ) {
          // Window exceeded: persist the union buffered so far and start a
          // fresh window from this update. The read path merges across lines,
          // so splitting the union over periodic snapshots loses nothing.
          this.writeToLocalCache(sessionId, this.buildMergedEntry(existing));
          cache.set(tcu.toolCallId, {
            latestEntry: entry,
            mergedUpdate: { ...tcu.update },
            bufferedAt: Date.now(),
          });
        } else if (existing) {
          Object.assign(existing.mergedUpdate, tcu.update);
          existing.latestEntry = entry;
        } else {
          cache.set(tcu.toolCallId, {
            latestEntry: entry,
            mergedUpdate: { ...tcu.update },
            bufferedAt: Date.now(),
          });
        }
      } else {
        if (tcu?.terminal) {
          // Merge the terminal update into any buffered union so fields only
          // carried by earlier snapshots (rawInput, edit diffs) still reach
          // the local cache; later fields win, so status/rawOutput come from
          // the terminal update itself.
          const buffered = session.toolUpdateCache.get(tcu.toolCallId);
          session.toolUpdateCache.delete(tcu.toolCallId);
          if (buffered) {
            Object.assign(buffered.mergedUpdate, tcu.update);
            buffered.latestEntry = entry;
            this.writeToLocalCache(sessionId, this.buildMergedEntry(buffered));
          } else {
            this.writeToLocalCache(sessionId, entry);
          }
        } else {
          this.flushToolUpdateCache(sessionId, session);
          this.writeToLocalCache(sessionId, entry);
        }
      }

      if (this.posthogAPI) {
        this.queueForApiLog(sessionId, session, entry, tcu);
      }
    } catch {
      this.logger.warn("Failed to parse raw line for persistence", {
        taskId: session.context.taskId,
        runId: session.context.runId,
        lineLength: line.length,
      });
    }
  }

  async flush(
    sessionId: string,
    { coalesce = false }: { coalesce?: boolean } = {},
  ): Promise<void> {
    if (coalesce) {
      const session = this.sessions.get(sessionId);
      if (session) {
        this.emitCoalescedMessage(sessionId, session);
        this.drainRawInputSnapshots(sessionId, session);
      }
    }

    // Serialize flushes per session
    const prev = this.flushQueues.get(sessionId) ?? Promise.resolve();
    const next = prev.catch(() => {}).then(() => this._doFlush(sessionId));
    this.flushQueues.set(sessionId, next);
    next.finally(() => {
      if (this.flushQueues.get(sessionId) === next) {
        this.flushQueues.delete(sessionId);
      }
    });
    return next;
  }

  private async _doFlush(sessionId: string): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) {
      this.logger.warn("flush: no session found", { sessionId });
      return;
    }

    const pending = this.pendingEntries.get(sessionId);
    if (!this.posthogAPI || !pending?.length) {
      return;
    }

    this.pendingEntries.delete(sessionId);
    const timeout = this.flushTimeouts.get(sessionId);
    if (timeout) {
      clearTimeout(timeout);
      this.flushTimeouts.delete(sessionId);
    }

    this.lastFlushAttemptTime.set(sessionId, Date.now());

    try {
      await this.posthogAPI.appendTaskRunLog(
        session.context.taskId,
        session.context.runId,
        pending,
      );
      this.retryCounts.set(sessionId, 0);
    } catch (error) {
      const retryCount = (this.retryCounts.get(sessionId) ?? 0) + 1;
      this.retryCounts.set(sessionId, retryCount);

      if (retryCount >= SessionLogWriter.MAX_FLUSH_RETRIES) {
        this.logger.error(
          `Dropping ${pending.length} session log entries after ${retryCount} failed flush attempts`,
          {
            taskId: session.context.taskId,
            runId: session.context.runId,
            maxRetries: SessionLogWriter.MAX_FLUSH_RETRIES,
            errorDetail: serializeError(error),
          },
        );
        this.retryCounts.set(sessionId, 0);
      } else {
        if (retryCount === 1) {
          this.logger.warn(
            `Failed to persist session logs, will retry (up to ${SessionLogWriter.MAX_FLUSH_RETRIES} attempts)`,
            {
              taskId: session.context.taskId,
              runId: session.context.runId,
              error: error instanceof Error ? error.message : String(error),
            },
          );
        }
        const currentPending = this.pendingEntries.get(sessionId) ?? [];
        this.pendingEntries.set(sessionId, [...pending, ...currentPending]);
        this.scheduleFlush(sessionId);
      }
    }
  }

  private emitToSinks(sessionId: string, entry: StoredNotification): void {
    for (const sink of this.sinks) {
      try {
        sink.append(sessionId, entry);
      } catch (error) {
        // Warn once per sink: a broken sink at streaming rate would otherwise
        // flood the console without ever affecting persistence.
        if (!this.warnedSinks.has(sink)) {
          this.warnedSinks.add(sink);
          this.logger.warn(
            "Session log sink failed; suppressing further errors from this sink",
            { error: serializeError(error) },
          );
        }
      }
    }
  }

  private getUpdate(
    message: Record<string, unknown>,
  ): Record<string, unknown> | undefined {
    const params = message.params as Record<string, unknown> | undefined;
    return params?.update as Record<string, unknown> | undefined;
  }

  private getSessionUpdateType(
    message: Record<string, unknown>,
  ): string | undefined {
    if (message.method !== "session/update") return undefined;
    return this.getUpdate(message)?.sessionUpdate as string | undefined;
  }

  private isDirectAgentMessage(message: Record<string, unknown>): boolean {
    return this.getSessionUpdateType(message) === "agent_message";
  }

  private toolCallUpdateInfo(message: Record<string, unknown>): {
    toolCallId: string;
    terminal: boolean;
    update: Record<string, unknown>;
  } | null {
    if (this.getSessionUpdateType(message) !== "tool_call_update") return null;
    const update = this.getUpdate(message);
    const toolCallId = update?.toolCallId;
    if (!update || typeof toolCallId !== "string") return null;
    const status = update.status;
    return {
      toolCallId,
      terminal: status === "completed" || status === "failed",
      update,
    };
  }

  /**
   * Rebuild the buffered update's entry around the merged union. Builds a
   * fresh object: the buffered `latestEntry` is also queued on the API path
   * and must not be mutated.
   */
  private buildMergedEntry(buffered: BufferedToolUpdate): StoredNotification {
    const { notification } = buffered.latestEntry;
    return {
      ...buffered.latestEntry,
      notification: {
        ...notification,
        params: { ...notification.params, update: buffered.mergedUpdate },
      },
    };
  }

  /** Write any buffered tool-update unions to the local cache, in order. */
  private flushToolUpdateCache(sessionId: string, session: SessionState): void {
    if (session.toolUpdateCache.size === 0) return;
    for (const buffered of session.toolUpdateCache.values()) {
      this.writeToLocalCache(sessionId, this.buildMergedEntry(buffered));
    }
    session.toolUpdateCache.clear();
  }

  private queueForApiLog(
    sessionId: string,
    session: SessionState,
    entry: StoredNotification,
    tcu: { toolCallId: string; update: Record<string, unknown> } | null,
  ): void {
    if (tcu && this.isRawInputOnlyUpdate(tcu.update)) {
      session.pendingRawInputSnapshots.set(tcu.toolCallId, entry);
      return;
    }
    if (tcu) {
      const buffered = session.pendingRawInputSnapshots.get(tcu.toolCallId);
      if (buffered) {
        session.pendingRawInputSnapshots.delete(tcu.toolCallId);
        if (tcu.update.rawInput === undefined) {
          this.pushPendingEntry(sessionId, buffered);
        }
      }
    }
    this.pushPendingEntry(sessionId, entry);
  }

  private isRawInputOnlyUpdate(update: Record<string, unknown>): boolean {
    if (update.rawInput === undefined) return false;
    return Object.keys(update).every(
      (key) =>
        key === "sessionUpdate" || key === "toolCallId" || key === "rawInput",
    );
  }

  private pushPendingEntry(sessionId: string, entry: StoredNotification): void {
    const pending = this.pendingEntries.get(sessionId) ?? [];
    pending.push(entry);
    this.pendingEntries.set(sessionId, pending);
    this.scheduleFlush(sessionId);
  }

  private drainRawInputSnapshots(
    sessionId: string,
    session: SessionState,
  ): void {
    if (session.pendingRawInputSnapshots.size === 0) return;
    for (const entry of session.pendingRawInputSnapshots.values()) {
      this.pushPendingEntry(sessionId, entry);
    }
    session.pendingRawInputSnapshots.clear();
  }

  private isAgentMessageChunk(message: Record<string, unknown>): boolean {
    return this.getSessionUpdateType(message) === "agent_message_chunk";
  }

  private isEmptyThoughtChunk(message: Record<string, unknown>): boolean {
    if (this.getSessionUpdateType(message) !== "agent_thought_chunk") {
      return false;
    }
    const content = this.getUpdate(message)?.content;
    if (!content) return true;
    return isEmptyContentBlock(content);
  }

  private extractChunkText(message: Record<string, unknown>): string {
    const content = this.getUpdate(message)?.content as
      | { type: string; text?: string }
      | undefined;
    if (content?.type === "text" && content.text) {
      return content.text;
    }
    return "";
  }

  private emitCoalescedMessage(sessionId: string, session: SessionState): void {
    if (!session.chunkBuffer) return;

    const { text, firstTimestamp } = session.chunkBuffer;
    session.chunkBuffer = undefined;
    session.lastAgentMessage = text;
    session.currentTurnMessages.push(text);

    const entry: StoredNotification = {
      type: "notification",
      timestamp: firstTimestamp,
      notification: {
        jsonrpc: "2.0",
        method: "session/update",
        params: {
          update: {
            sessionUpdate: "agent_message",
            content: { type: "text", text },
          },
        },
      },
    };

    this.writeToLocalCache(sessionId, entry);

    if (this.posthogAPI) {
      this.pushPendingEntry(sessionId, entry);
    }
  }

  getLastAgentMessage(sessionId: string): string | undefined {
    return this.sessions.get(sessionId)?.lastAgentMessage;
  }

  getFullAgentResponse(sessionId: string): string | undefined {
    const session = this.sessions.get(sessionId);
    if (!session || session.currentTurnMessages.length === 0) return undefined;

    if (session.chunkBuffer) {
      this.logger.warn(
        "getFullAgentResponse called with non-empty chunk buffer",
        {
          sessionId,
          bufferedLength: session.chunkBuffer.text.length,
        },
      );
    }

    return session.currentTurnMessages.join("\n\n");
  }

  /**
   * Returns the ordered assistant text blocks for the current turn — one entry
   * per message between tool calls. The last entry is the text after the final
   * tool_use (the actual answer to the user).
   *
   * The Slack relay uses this so the backend can post only the last block
   * instead of every interim "Let me check…" narration.
   */
  getAgentResponseParts(sessionId: string): string[] | undefined {
    const session = this.sessions.get(sessionId);
    if (!session || session.currentTurnMessages.length === 0) return undefined;

    if (session.chunkBuffer) {
      this.logger.warn(
        "getAgentResponseParts called with non-empty chunk buffer",
        {
          sessionId,
          bufferedLength: session.chunkBuffer.text.length,
        },
      );
    }

    return [...session.currentTurnMessages];
  }

  resetTurnMessages(sessionId: string): void {
    const session = this.sessions.get(sessionId);
    if (session) {
      session.currentTurnMessages = [];
    }
  }

  private extractAgentMessageText(
    message: Record<string, unknown>,
  ): string | null {
    if (message.method !== "session/update") {
      return null;
    }

    const update = this.getUpdate(message);
    if (update?.sessionUpdate !== "agent_message") {
      return null;
    }

    const content = update.content as
      | { type?: string; text?: string }
      | undefined;
    if (content?.type === "text" && typeof content.text === "string") {
      const trimmed = content.text.trim();
      return trimmed.length > 0 ? trimmed : null;
    }

    if (typeof update.message === "string") {
      const trimmed = update.message.trim();
      return trimmed.length > 0 ? trimmed : null;
    }

    return null;
  }

  private scheduleFlush(sessionId: string): void {
    const existing = this.flushTimeouts.get(sessionId);
    if (existing) clearTimeout(existing);

    const retryCount = this.retryCounts.get(sessionId) ?? 0;
    const lastAttempt = this.lastFlushAttemptTime.get(sessionId) ?? 0;
    const elapsed = Date.now() - lastAttempt;

    let delay: number;
    if (retryCount > 0) {
      // Exponential backoff on retries: FLUSH_DEBOUNCE_MS * 2^retryCount, capped
      delay = Math.min(
        SessionLogWriter.FLUSH_DEBOUNCE_MS * 2 ** retryCount,
        SessionLogWriter.MAX_RETRY_DELAY_MS,
      );
    } else if (elapsed >= SessionLogWriter.FLUSH_MAX_INTERVAL_MS) {
      // If we've been accumulating for longer than the max interval, flush immediately
      delay = 0;
    } else {
      delay = SessionLogWriter.FLUSH_DEBOUNCE_MS;
    }

    const timeout = setTimeout(() => this.flush(sessionId), delay);
    this.flushTimeouts.set(sessionId, timeout);
  }

  private writeToLocalCache(
    sessionId: string,
    entry: StoredNotification,
  ): void {
    if (!this.localCachePath) return;

    const session = this.sessions.get(sessionId);
    if (!session) return;

    const logPath = path.join(
      this.localCachePath,
      "sessions",
      session.context.runId,
      "logs.ndjson",
    );

    try {
      fs.appendFileSync(logPath, `${JSON.stringify(entry)}\n`);
    } catch (error) {
      this.logger.warn("Failed to write to local cache", {
        taskId: session.context.taskId,
        runId: session.context.runId,
        logPath,
        error,
      });
    }
  }

  static async cleanupOldSessions(localCachePath: string): Promise<number> {
    const sessionsDir = path.join(localCachePath, "sessions");
    let deleted = 0;
    try {
      const entries = await fsp.readdir(sessionsDir);
      const now = Date.now();
      for (const entry of entries) {
        const entryPath = path.join(sessionsDir, entry);
        try {
          const stats = await fsp.stat(entryPath);
          if (
            stats.isDirectory() &&
            now - stats.birthtimeMs > SessionLogWriter.SESSIONS_MAX_AGE_MS
          ) {
            await fsp.rm(entryPath, { recursive: true, force: true });
            deleted++;
          }
        } catch {
          // Skip entries we can't stat
        }
      }
    } catch {
      // Sessions dir may not exist yet
    }
    return deleted;
  }
}

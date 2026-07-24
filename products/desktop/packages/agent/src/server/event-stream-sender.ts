import { Buffer } from "node:buffer";
import type { Logger } from "../utils/logger";
import {
  createNodeStreamingUpload,
  type StreamingUpload,
  type StreamingUploadFactory,
} from "./streaming-upload";

interface TaskRunEventStreamSenderConfig {
  apiUrl: string;
  // Base URL for the event-ingest POST only; falls back to apiUrl (Django path) when unset.
  eventIngestBaseUrl?: string;
  keepProxyStreamOpen?: boolean;
  projectId: number;
  taskId: string;
  runId: string;
  token: string;
  logger: Logger;
  maxBufferedEvents?: number;
  flushDelayMs?: number;
  retryDelayMs?: number;
  requestTimeoutMs?: number;
  stopTimeoutMs?: number;
  maxEventBytes?: number;
  maxStreamEvents?: number;
  maxStreamBytes?: number;
  streamWindowMs?: number;
  createStreamingUpload?: StreamingUploadFactory;
}

interface EventEnvelope {
  seq: number;
  event: Record<string, unknown>;
}

interface IngestResponse {
  last_accepted_seq?: unknown;
}

interface ActiveStream {
  abortController: AbortController;
  upload: StreamingUpload;
  responsePromise: Promise<Response>;
  startedAtMs: number;
  sentThroughSeq: number;
  sentEvents: number;
  sentBytes: number;
  windowTimer: ReturnType<typeof setTimeout> | null;
}

const DEFAULT_MAX_BUFFERED_EVENTS = 20_000;
const DEFAULT_MAX_STREAM_EVENTS = 900;
const DEFAULT_MAX_STREAM_BYTES = 4_000_000;
const DEFAULT_MAX_EVENT_BYTES = 900_000;
const DEFAULT_FLUSH_DELAY_MS = 0;
const DEFAULT_RETRY_DELAY_MS = 1_000;
const DEFAULT_REQUEST_TIMEOUT_MS = 10_000;
const DEFAULT_STOP_TIMEOUT_MS = 30_000;
const DEFAULT_STREAM_WINDOW_MS = 5 * 60 * 1_000;
const STREAM_COMPLETE_CONTROL_TYPE = "_posthog/stream_complete";

export class TaskRunEventStreamSender {
  private readonly ingestUrl: string;
  private readonly maxBufferedEvents: number;
  private readonly maxStreamEvents: number;
  private readonly maxStreamBytes: number;
  private readonly maxEventBytes: number;
  private readonly flushDelayMs: number;
  private readonly retryDelayMs: number;
  private readonly requestTimeoutMs: number;
  private readonly stopTimeoutMs: number;
  private readonly streamWindowMs: number;
  private readonly usingProxy: boolean;
  private readonly keepProxyStreamOpen: boolean;
  private readonly createStreamingUpload: StreamingUploadFactory;
  private readonly encoder = new TextEncoder();
  private sequence = 0;
  private lastKnownAcceptedSeq = 0;
  private bufferedEvents: EventEnvelope[] = [];
  private flushTimer: ReturnType<typeof setTimeout> | null = null;
  private flushPromise: Promise<void> | null = null;
  private streamClosePromise: Promise<void> | null = null;
  private activeStream: ActiveStream | null = null;
  private stopPromise: Promise<void> | null = null;
  private stopped = false;
  private sequenceSynced = false;
  private sequenceInitialized = false;
  private transportCompleted = false;
  private droppedBeforeSequenceCount = 0;
  private bufferRevision = 0;

  constructor(private readonly config: TaskRunEventStreamSenderConfig) {
    const usingProxy = Boolean(config.eventIngestBaseUrl);
    const ingestBase = (config.eventIngestBaseUrl ?? config.apiUrl).replace(
      /\/$/,
      "",
    );
    this.ingestUrl = usingProxy
      ? `${ingestBase}/v1/runs/${encodeURIComponent(config.runId)}/ingest`
      : `${ingestBase}/api/projects/${config.projectId}/tasks/${encodeURIComponent(
          config.taskId,
        )}/runs/${encodeURIComponent(config.runId)}/event_stream/`;
    config.logger.info("Event ingest target resolved", {
      ingestUrl: this.ingestUrl,
      routedToProxy: usingProxy,
    });
    this.maxBufferedEvents =
      config.maxBufferedEvents ?? DEFAULT_MAX_BUFFERED_EVENTS;
    this.maxStreamEvents = config.maxStreamEvents ?? DEFAULT_MAX_STREAM_EVENTS;
    this.maxStreamBytes = config.maxStreamBytes ?? DEFAULT_MAX_STREAM_BYTES;
    this.maxEventBytes = config.maxEventBytes ?? DEFAULT_MAX_EVENT_BYTES;
    this.flushDelayMs = config.flushDelayMs ?? DEFAULT_FLUSH_DELAY_MS;
    this.retryDelayMs = config.retryDelayMs ?? DEFAULT_RETRY_DELAY_MS;
    this.requestTimeoutMs =
      config.requestTimeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS;
    this.stopTimeoutMs = config.stopTimeoutMs ?? DEFAULT_STOP_TIMEOUT_MS;
    this.streamWindowMs = config.streamWindowMs ?? DEFAULT_STREAM_WINDOW_MS;
    this.usingProxy = usingProxy;
    this.keepProxyStreamOpen = config.keepProxyStreamOpen ?? false;
    this.createStreamingUpload =
      config.createStreamingUpload ?? createNodeStreamingUpload;
  }

  enqueue(event: Record<string, unknown>): void {
    if (this.stopped) return;

    if (!this.canAcceptEvent(event)) {
      return;
    }

    const envelope: EventEnvelope = {
      seq: ++this.sequence,
      event,
    };
    this.bufferedEvents.push(envelope);
    this.scheduleFlush();
  }

  async stop(): Promise<void> {
    if (this.stopPromise) {
      await this.stopPromise;
      return;
    }

    this.stopped = true;

    if (this.flushTimer) {
      clearTimeout(this.flushTimer);
      this.flushTimer = null;
    }

    this.stopPromise = this.drainForStop();
    await this.stopPromise;
  }

  private scheduleFlush(delayMs = this.flushDelayMs): void {
    if (this.flushTimer || this.flushPromise || this.stopped) return;

    this.flushTimer = setTimeout(() => {
      this.flushTimer = null;
      void this.flush();
    }, delayMs);
  }

  private async drainForStop(): Promise<void> {
    const startedAtMs = Date.now();
    const deadlineAtMs = startedAtMs + this.stopTimeoutMs;

    while (!this.transportCompleted) {
      const previousLength = this.bufferedEvents.length;
      const previousRevision = this.bufferRevision;

      try {
        await this.flush();
        await this.writeCompletionLine();
        await this.closeActiveStream();
        this.transportCompleted = true;
        return;
      } catch (error) {
        this.config.logger.warn(
          "Task run event ingest stop request failed",
          this.describeError(error),
        );
      }

      const madeProgress =
        this.bufferedEvents.length < previousLength ||
        this.bufferRevision !== previousRevision;
      if (!madeProgress && !(await this.waitBeforeStopRetry(deadlineAtMs))) {
        this.warnStopDeadlineReached(startedAtMs);
        return;
      }

      if (Date.now() >= deadlineAtMs && !this.transportCompleted) {
        this.warnStopDeadlineReached(startedAtMs);
        return;
      }
    }
  }

  private async flush(): Promise<boolean> {
    if (this.flushPromise) {
      await this.flushPromise.catch(() => undefined);
    }

    if (this.bufferedEvents.length === 0) {
      return true;
    }

    const previousBufferLength = this.bufferedEvents.length;
    const flushPromise = this.flushBufferedEvents();
    this.flushPromise = flushPromise;

    try {
      await flushPromise;
      // The ingress ahead of the agent-proxy only forwards the request body once the
      // upload closes, so close per drained batch to avoid stranding buffered events.
      if (!this.stopped && this.usingProxy && !this.keepProxyStreamOpen) {
        await this.closeActiveStream();
      }
      return this.bufferedEvents.length < previousBufferLength;
    } catch (error) {
      this.config.logger.warn(
        "Task run event ingest stream write failed",
        this.describeError(error),
      );
      await this.abortActiveStream();
      if (!this.stopped) {
        this.scheduleFlush(this.retryDelayMs);
      }
      return false;
    } finally {
      if (this.flushPromise === flushPromise) {
        this.flushPromise = null;
      }
      if (!this.stopped && this.hasUnwrittenBufferedEvents()) {
        this.scheduleFlush(0);
      }
    }
  }

  private async flushBufferedEvents(): Promise<void> {
    while (true) {
      const stream = await this.ensureActiveStream();
      const nextEvent = this.bufferedEvents.find(
        (event) => event.seq > stream.sentThroughSeq,
      );
      if (!nextEvent) {
        return;
      }

      const line = `${this.serializeEnvelope(nextEvent)}\n`;
      const lineBytes = Buffer.byteLength(line, "utf8");
      if (this.shouldRollStreamBeforeWriting(stream, lineBytes)) {
        await this.closeActiveStream();
        continue;
      }

      await stream.upload.write(this.encoder.encode(line));
      stream.sentThroughSeq = nextEvent.seq;
      stream.sentEvents += 1;
      stream.sentBytes += lineBytes;
    }
  }

  private hasUnwrittenBufferedEvents(): boolean {
    const sentThroughSeq =
      this.activeStream?.sentThroughSeq ?? this.lastKnownAcceptedSeq;
    return this.bufferedEvents.some((event) => event.seq > sentThroughSeq);
  }

  private async writeCompletionLine(): Promise<void> {
    await this.syncSequenceWithServer();

    while (true) {
      const stream = await this.ensureActiveStream();
      const hasUnwrittenEvents = this.bufferedEvents.some(
        (event) => event.seq > stream.sentThroughSeq,
      );
      if (hasUnwrittenEvents) {
        await this.flushBufferedEvents();
        continue;
      }

      const line = `${JSON.stringify({
        type: STREAM_COMPLETE_CONTROL_TYPE,
        final_seq: this.sequence,
      })}\n`;
      const lineBytes = Buffer.byteLength(line, "utf8");
      if (
        this.shouldRollStreamBeforeWriting(stream, lineBytes, {
          ignoreEventCount: true,
        })
      ) {
        await this.closeActiveStream();
        continue;
      }

      await stream.upload.write(this.encoder.encode(line));
      stream.sentBytes += lineBytes;
      return;
    }
  }

  private shouldRollStreamBeforeWriting(
    stream: ActiveStream,
    lineBytes: number,
    options: { ignoreEventCount?: boolean } = {},
  ): boolean {
    if (
      !options.ignoreEventCount &&
      stream.sentEvents > 0 &&
      stream.sentEvents >= this.maxStreamEvents
    ) {
      return true;
    }
    if (
      stream.sentBytes > 0 &&
      stream.sentBytes + lineBytes > this.maxStreamBytes
    ) {
      return true;
    }
    return Date.now() - stream.startedAtMs >= this.streamWindowMs;
  }

  private async ensureActiveStream(): Promise<ActiveStream> {
    if (this.streamClosePromise) {
      await this.streamClosePromise.catch(() => undefined);
    }

    if (this.activeStream) {
      return this.activeStream;
    }

    await this.syncSequenceWithServer();

    const abortController = new AbortController();
    const upload = this.createStreamingUpload({
      url: this.ingestUrl,
      headers: this.buildHeaders(),
      abortController,
    });
    const activeStream: ActiveStream = {
      abortController,
      upload,
      responsePromise: upload.responsePromise,
      startedAtMs: Date.now(),
      sentThroughSeq: this.lastKnownAcceptedSeq,
      sentEvents: 0,
      sentBytes: 0,
      windowTimer: null,
    };
    this.activeStream = activeStream;
    this.scheduleStreamWindowClose(activeStream);
    upload.responsePromise.catch((error) => {
      void this.handleActiveStreamResponseFailure(activeStream, error);
    });
    return activeStream;
  }

  private scheduleStreamWindowClose(
    stream: ActiveStream,
    delayOverrideMs?: number,
  ): void {
    this.clearStreamWindowClose(stream);
    // Rotate long-lived uploads even when idle: a transport boundary, not a batching window.
    const delayMs =
      delayOverrideMs ??
      Math.max(0, stream.startedAtMs + this.streamWindowMs - Date.now());
    stream.windowTimer = setTimeout(() => {
      stream.windowTimer = null;
      void this.closeExpiredStream(stream);
    }, delayMs);
  }

  private clearStreamWindowClose(stream: ActiveStream): void {
    if (!stream.windowTimer) {
      return;
    }
    clearTimeout(stream.windowTimer);
    stream.windowTimer = null;
  }

  private async closeExpiredStream(stream: ActiveStream): Promise<void> {
    if (this.activeStream !== stream || this.stopped) {
      return;
    }

    if (this.flushPromise) {
      this.scheduleStreamWindowClose(stream, 50);
      return;
    }

    try {
      await this.closeActiveStream();
    } catch (error) {
      this.config.logger.warn(
        "Task run event ingest stream window close failed",
        this.describeError(error),
      );
      if (!this.stopped && this.bufferedEvents.length > 0) {
        this.scheduleFlush(this.retryDelayMs);
      }
    }
  }

  private async handleActiveStreamResponseFailure(
    stream: ActiveStream,
    error: unknown,
  ): Promise<void> {
    if (this.activeStream !== stream) {
      return;
    }

    this.config.logger.warn(
      "Task run event ingest stream request failed",
      this.describeError(error),
    );
    try {
      await this.abortActiveStream();
    } catch (abortError) {
      this.config.logger.warn(
        "Task run event ingest stream abort failed",
        this.describeError(abortError),
      );
    }
    if (!this.stopped && this.bufferedEvents.length > 0) {
      this.scheduleFlush(this.retryDelayMs);
    }
  }

  private async closeActiveStream(): Promise<void> {
    if (this.streamClosePromise) {
      await this.streamClosePromise;
      return;
    }

    const stream = this.activeStream;
    if (!stream) {
      return;
    }

    const closePromise = this.closeStream(stream);
    this.streamClosePromise = closePromise;
    try {
      await closePromise;
    } finally {
      this.clearStreamWindowClose(stream);
      if (this.activeStream === stream) {
        this.activeStream = null;
      }
      if (this.streamClosePromise === closePromise) {
        this.streamClosePromise = null;
      }
    }
  }

  private async closeStream(stream: ActiveStream): Promise<void> {
    try {
      await stream.upload.close();
    } catch (error) {
      stream.abortController.abort();
      this.sequenceSynced = false;
      throw error;
    }

    let response: Response;
    try {
      response = await this.waitForResponseWithTimeout(
        stream.responsePromise,
        stream.abortController,
      );
    } catch (error) {
      stream.abortController.abort();
      this.sequenceSynced = false;
      throw error;
    }

    await this.applyIngestResponse(response, "Event ingest stream");
    this.sequenceSynced = true;
  }

  private async abortActiveStream(): Promise<void> {
    const stream = this.activeStream;
    if (!stream) {
      return;
    }

    stream.abortController.abort();
    this.clearStreamWindowClose(stream);
    try {
      await stream.upload.abort();
    } catch {
      // The upload may already be closed by the transport after the abort.
    } finally {
      if (this.activeStream === stream) {
        this.activeStream = null;
      }
      this.sequenceSynced = false;
    }
  }

  private async waitBeforeStopRetry(deadlineAtMs: number): Promise<boolean> {
    const remainingMs = deadlineAtMs - Date.now();
    if (remainingMs <= 0) {
      return false;
    }

    await new Promise((resolve) =>
      setTimeout(resolve, Math.min(this.retryDelayMs, remainingMs)),
    );
    return Date.now() < deadlineAtMs;
  }

  private warnStopDeadlineReached(startedAtMs: number): void {
    this.config.logger.warn(
      "Task run event ingest stop deadline reached before fully completing transport",
      {
        remaining: this.bufferedEvents.length,
        stopTimeoutMs: this.stopTimeoutMs,
        elapsedMs: Date.now() - startedAtMs,
      },
    );
  }

  private async syncSequenceWithServer(): Promise<void> {
    if (this.sequenceSynced) return;

    const response = await this.fetchWithTimeout({
      method: "POST",
      headers: this.buildHeaders(),
      body: "",
    });
    const responseBody = await this.parseResponse(response);

    if (!response.ok) {
      throw new Error(
        `Event ingest sequence sync returned HTTP ${response.status}: ${responseBody.text.slice(0, 300)}`,
      );
    }

    const lastAcceptedSeq = responseBody.parsed?.last_accepted_seq;
    if (typeof lastAcceptedSeq === "number" && lastAcceptedSeq > 0) {
      if (!this.sequenceInitialized) {
        this.bufferedEvents = this.bufferedEvents.map((event) => ({
          ...event,
          seq: event.seq + lastAcceptedSeq,
        }));
        this.sequence += lastAcceptedSeq;
        this.bufferRevision += 1;
      } else {
        this.acceptThrough(lastAcceptedSeq);
        if (lastAcceptedSeq > this.sequence) {
          this.sequence = lastAcceptedSeq;
        }
      }
      this.lastKnownAcceptedSeq = lastAcceptedSeq;
    }

    this.sequenceSynced = true;
    this.sequenceInitialized = true;
  }

  private async fetchWithTimeout(init: RequestInit): Promise<Response> {
    const abortController = new AbortController();
    const timeout = setTimeout(() => {
      abortController.abort();
    }, this.requestTimeoutMs);

    try {
      return await fetch(this.ingestUrl, {
        ...init,
        signal: abortController.signal,
      });
    } finally {
      clearTimeout(timeout);
    }
  }

  private async waitForResponseWithTimeout(
    responsePromise: Promise<Response>,
    abortController: AbortController,
  ): Promise<Response> {
    const timeout = setTimeout(() => {
      abortController.abort();
    }, this.requestTimeoutMs);

    try {
      return await responsePromise;
    } finally {
      clearTimeout(timeout);
    }
  }

  private async applyIngestResponse(
    response: Response,
    label: string,
  ): Promise<void> {
    const responseBody = await this.parseResponse(response);
    const lastAcceptedSeq = responseBody.parsed?.last_accepted_seq;
    if (typeof lastAcceptedSeq === "number") {
      this.acceptThrough(lastAcceptedSeq);
      if (lastAcceptedSeq > this.sequence) {
        this.sequence = lastAcceptedSeq;
      }
      this.lastKnownAcceptedSeq = lastAcceptedSeq;
      if (response.status === 409) {
        this.rebaseBufferedEvents(lastAcceptedSeq);
      }
    }

    if (!response.ok) {
      throw new Error(
        `${label} returned HTTP ${response.status}: ${responseBody.text.slice(0, 300)}`,
      );
    }
  }

  private acceptThrough(lastAcceptedSeq: number): void {
    const previousLength = this.bufferedEvents.length;
    this.bufferedEvents = this.bufferedEvents.filter(
      (event) => event.seq > lastAcceptedSeq,
    );
    if (this.bufferedEvents.length !== previousLength) {
      this.bufferRevision += 1;
    }
  }

  private buildHeaders(): Record<string, string> {
    return {
      Authorization: `Bearer ${this.config.token}`,
      "Content-Type": "application/x-ndjson",
    };
  }

  private rebaseBufferedEvents(lastAcceptedSeq: number): void {
    let nextSeq = lastAcceptedSeq + 1;
    this.bufferedEvents = this.bufferedEvents.map((event) => ({
      ...event,
      seq: nextSeq++,
    }));
    this.sequence = nextSeq - 1;
    this.sequenceSynced = true;
    this.sequenceInitialized = true;
    this.lastKnownAcceptedSeq = lastAcceptedSeq;
    this.bufferRevision += 1;
  }

  private async parseResponse(
    response: Response,
  ): Promise<{ parsed: IngestResponse | null; text: string }> {
    const text = await response.text();
    if (!text) {
      return { parsed: null, text };
    }

    try {
      return { parsed: JSON.parse(text) as IngestResponse, text };
    } catch {
      return { parsed: null, text };
    }
  }

  private canAcceptEvent(event: Record<string, unknown>): boolean {
    const eventBytes = Buffer.byteLength(
      this.serializeEnvelope({ seq: this.sequence + 1, event }),
      "utf8",
    );
    if (eventBytes > this.maxEventBytes) {
      this.config.logger.warn("Dropped oversized task run event", {
        eventBytes,
        maxEventBytes: this.maxEventBytes,
      });
      return false;
    }

    if (this.bufferedEvents.length >= this.maxBufferedEvents) {
      this.droppedBeforeSequenceCount += 1;
      if (
        this.droppedBeforeSequenceCount === 1 ||
        this.droppedBeforeSequenceCount % 100 === 0
      ) {
        this.config.logger.warn(
          "Dropped task run event before assigning sequence due to backpressure",
          {
            dropped: this.droppedBeforeSequenceCount,
            maxBufferedEvents: this.maxBufferedEvents,
          },
        );
      }
      return false;
    }

    if (this.droppedBeforeSequenceCount > 0) {
      this.config.logger.info("Task run event ingest recovered after drops", {
        dropped: this.droppedBeforeSequenceCount,
      });
      this.droppedBeforeSequenceCount = 0;
    }

    return true;
  }

  private serializeEnvelope(envelope: EventEnvelope): string {
    return JSON.stringify({ seq: envelope.seq, event: envelope.event });
  }

  private describeError(error: unknown): unknown {
    if (error instanceof Error) {
      return { message: error.message, stack: error.stack };
    }
    return error;
  }
}

/**
 * Shared background-job primitive: run async work without blocking the tool
 * call that started it, then deliver the outcome back into the conversation
 * via `pi.sendMessage`.
 *
 * This is the one place that decides *how* a background result gets back to
 * the model, so every caller (subagent, workflow, future tools) behaves the
 * same way instead of each inventing its own delivery policy:
 *
 * - `deliverAs: "steer"` + `triggerTurn: true`, always, unconditionally.
 *   Per pi's own documented semantics, `triggerTurn` only takes effect when
 *   the agent is idle — so this single flag combination already implements
 *   "steer the message in if a turn is running, wake the session up if not."
 *   There is no separate branch to get wrong, and no need for callers (or
 *   this module) to inspect whether a turn is currently in flight.
 *
 * The job registry is a plain in-memory `Map`, alive only for the lifetime of
 * the process — no persistence, no resume across restarts. That mirrors the
 * same "no evidence of need yet" call made for workflow's resumability gap;
 * this can grow into something sturdier later if it turns out to matter.
 */

import { randomUUID } from "node:crypto";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

type SendMessageInput = Parameters<ExtensionAPI["sendMessage"]>[0];

export const BACKGROUND_JOB_MESSAGE_TYPE = "background-job";

export type BackgroundJobStatus = "completed" | "failed" | "cancelled";

export interface BackgroundJobDetails {
  jobId: string;
  label: string;
  status: BackgroundJobStatus;
  durationMs: number;
}

export interface BackgroundJobSummary {
  jobId: string;
  label: string;
  startedAt: number;
}

export interface StartBackgroundJobOptions<T> {
  /** Only `sendMessage` is used; accepting the full API keeps call sites simple. */
  pi: Pick<ExtensionAPI, "sendMessage">;
  /** Human-readable description shown in the started/completed/failed messages. */
  label: string;
  /**
   * Upstream signal from the tool call that's handing this off (e.g. the
   * `execute()` call's own `signal`). If the tool call itself is aborted in
   * the brief window before it returns, the background job is aborted too.
   */
  signal?: AbortSignal;
  /** The actual async work. Must react to `signal` to make cancellation real. */
  work: (signal: AbortSignal) => Promise<T>;
  /** Body text for the completion message, built from the resolved value. */
  onSuccess: (result: T) => string;
  /** Body text for the failure message. Defaults to `String(error)`. */
  onFailure?: (error: unknown) => string;
}

export interface BackgroundJobStart {
  jobId: string;
  /** Ack text for the tool call's own immediate result. */
  ack: string;
}

interface JobEntry {
  jobId: string;
  label: string;
  startedAt: number;
  controller: AbortController;
}

const jobs = new Map<string, JobEntry>();

function statusLabel(status: BackgroundJobStatus): string {
  switch (status) {
    case "completed":
      return "\u2713 Background job finished";
    case "failed":
      return "\u2717 Background job failed";
    case "cancelled":
      return "\u25cb Background job cancelled";
  }
}

function formatDuration(durationMs: number): string {
  if (durationMs < 1000) return `${durationMs}ms`;
  const seconds = durationMs / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  return `${minutes}m${remainder}s`;
}

function buildMessage(
  status: BackgroundJobStatus,
  label: string,
  jobId: string,
  durationMs: number,
  body: string,
): SendMessageInput {
  return {
    customType: BACKGROUND_JOB_MESSAGE_TYPE,
    content: `${statusLabel(status)}: "${label}" (${formatDuration(durationMs)})\n\n${body}`,
    display: true,
    details: { jobId, label, status, durationMs },
  };
}

/**
 * Kick off `work` without awaiting it, and return an immediate ack. The
 * caller's tool call should return `ack` right away instead of blocking.
 */
export function startBackgroundJob<T>(
  options: StartBackgroundJobOptions<T>,
): BackgroundJobStart {
  const jobId = randomUUID();
  const controller = new AbortController();
  if (options.signal) {
    if (options.signal.aborted) {
      controller.abort();
    } else {
      options.signal.addEventListener("abort", () => controller.abort(), {
        once: true,
      });
    }
  }
  const startedAt = Date.now();
  jobs.set(jobId, { jobId, label: options.label, startedAt, controller });

  options.work(controller.signal).then(
    (result) => {
      jobs.delete(jobId);
      options.pi.sendMessage(
        buildMessage(
          "completed",
          options.label,
          jobId,
          Date.now() - startedAt,
          options.onSuccess(result),
        ),
        { deliverAs: "steer", triggerTurn: true },
      );
    },
    (error) => {
      jobs.delete(jobId);
      const status: BackgroundJobStatus = controller.signal.aborted
        ? "cancelled"
        : "failed";
      const body =
        status === "cancelled"
          ? "Cancelled before completion."
          : (options.onFailure ?? describeError)(error);
      options.pi.sendMessage(
        buildMessage(
          status,
          options.label,
          jobId,
          Date.now() - startedAt,
          body,
        ),
        { deliverAs: "steer", triggerTurn: true },
      );
    },
  );

  return {
    jobId,
    ack: `Started "${options.label}" in the background (job ${jobId}). I'll post the result here when it finishes — no need to wait or check back.`,
  };
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Returns `false` if no running job matches `jobId`. */
export function cancelBackgroundJob(jobId: string): boolean {
  const job = jobs.get(jobId);
  if (!job) return false;
  job.controller.abort();
  return true;
}

export function listBackgroundJobs(): BackgroundJobSummary[] {
  return [...jobs.values()]
    .map(({ jobId, label, startedAt }) => ({ jobId, label, startedAt }))
    .sort((a, b) => a.startedAt - b.startedAt);
}

/** Aborts every running job. Used on `session_shutdown` to avoid orphans. */
export function cancelAllBackgroundJobs(): void {
  for (const job of jobs.values()) job.controller.abort();
}

/** Test-only: clears the registry without aborting anything. */
export function __resetBackgroundJobsForTesting(): void {
  jobs.clear();
}

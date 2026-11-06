/**
 * Versioned on-disk run artifacts, written for every subagent run so its
 * final state and transcript are inspectable after the fact without the
 * parent process's in-memory state.
 *
 * Layout: `<runsDir>/<runId>/status.json`, `<runId>/events.jsonl`,
 * `<runId>/transcript.md`.
 */

import { randomUUID } from "node:crypto";
import * as fs from "node:fs";
import * as path from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import { truncateUtf8 } from "./text-truncate";

export const LIFECYCLE_ARTIFACT_VERSION = 1;

export type RunMode = "single" | "parallel";
export type RunState = "running" | "completed" | "failed" | "aborted";

export interface RunStatus {
  lifecycleArtifactVersion: number;
  runId: string;
  sessionId?: string;
  mode: RunMode;
  agents: string[];
  state: RunState;
  startedAt: number;
  endedAt?: number;
  durationMs?: number;
  totalTokens?: number;
  totalCost?: number;
  model?: string;
  error?: string;
  /** Truncated final output text, for a quick summary without replaying the full transcript. */
  resultSummary?: string;
}

export interface RunEvent {
  type: string;
  timestamp: number;
  [key: string]: unknown;
}

export function runsDirectory(): string {
  return path.join(getAgentDir(), "subagent-runs");
}

export function runDirectory(runId: string): string {
  return path.join(runsDirectory(), runId);
}

export function createRunId(): string {
  return randomUUID();
}

function writeJsonFileSync(filePath: string, data: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tmpPath = `${filePath}.tmp-${process.pid}`;
  fs.writeFileSync(tmpPath, JSON.stringify(data, null, 2));
  fs.renameSync(tmpPath, filePath);
}

export function startRun(
  status: Omit<RunStatus, "lifecycleArtifactVersion" | "state" | "startedAt">,
): RunStatus {
  const fullStatus: RunStatus = {
    lifecycleArtifactVersion: LIFECYCLE_ARTIFACT_VERSION,
    state: "running",
    startedAt: Date.now(),
    ...status,
  };
  writeStatus(fullStatus);
  appendEvent(status.runId, {
    type: "started",
    timestamp: fullStatus.startedAt,
  });
  return fullStatus;
}

export function writeStatus(status: RunStatus): void {
  writeJsonFileSync(
    path.join(runDirectory(status.runId), "status.json"),
    status,
  );
}

export function appendEvent(runId: string, event: RunEvent): void {
  const dir = runDirectory(runId);
  fs.mkdirSync(dir, { recursive: true });
  fs.appendFileSync(
    path.join(dir, "events.jsonl"),
    `${JSON.stringify(event)}\n`,
  );
}

export interface EndRunExtra {
  totalTokens?: number;
  totalCost?: number;
  model?: string;
  resultSummary?: string;
}

export function endRun(
  status: RunStatus,
  state: Exclude<RunState, "running">,
  error?: string,
  extra?: EndRunExtra,
): RunStatus {
  const endedAt = Date.now();
  const finalStatus: RunStatus = {
    ...status,
    ...extra,
    state,
    endedAt,
    durationMs: endedAt - status.startedAt,
    error,
  };
  writeStatus(finalStatus);
  appendEvent(status.runId, { type: state, timestamp: endedAt, error });
  return finalStatus;
}

export function transcriptPath(runId: string): string {
  return path.join(runDirectory(runId), "transcript.md");
}

const DEFAULT_MAX_TRANSCRIPT_BYTES = 5 * 1024 * 1024;

/**
 * Writes the run's transcript, capped so a very long-running or verbose
 * subagent can't grow an unbounded file on disk.
 */
export function writeTranscript(
  runId: string,
  markdown: string,
  maxBytes: number = DEFAULT_MAX_TRANSCRIPT_BYTES,
): void {
  const filePath = transcriptPath(runId);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });

  const { text, omittedBytes } = truncateUtf8(markdown, maxBytes);
  if (omittedBytes === 0) {
    fs.writeFileSync(filePath, markdown);
    return;
  }

  fs.writeFileSync(
    filePath,
    `${text}\n\n[transcript truncated: exceeded ${maxBytes} bytes; ${omittedBytes} bytes omitted]\n`,
  );
}

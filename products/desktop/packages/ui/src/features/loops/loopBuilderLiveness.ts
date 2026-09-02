import { isTerminalStatus } from "@posthog/shared/domain-types";
import type { LoopBuilderSession } from "./loopBuilderSessionStore";

// A fresh task can briefly report no run (or be absent from the summaries
// response) before its cloud run registers; don't treat that as ended.
export const FRESH_SESSION_GRACE_MS = 60_000;

export interface BuilderRunSummary {
  environment: string | null;
  status: string | null;
}

/** taskId -> latest run; a null value means the task exists but has no run,
 * an absent key means the summaries response doesn't know the task at all. */
export type BuilderRunSummaries = ReadonlyMap<string, BuilderRunSummary | null>;

export function isBuilderSessionEnded(
  session: LoopBuilderSession,
  summaries: BuilderRunSummaries,
  archivedTaskIds: ReadonlySet<string>,
  now: number,
): boolean {
  if (archivedTaskIds.has(session.taskId)) return true;
  const pastGrace = now - session.startedAt >= FRESH_SESSION_GRACE_MS;
  if (!summaries.has(session.taskId)) return pastGrace;
  const run = summaries.get(session.taskId) ?? null;
  if (!run) return pastGrace;
  if (run.environment !== "cloud") return true;
  return isTerminalStatus(run.status);
}

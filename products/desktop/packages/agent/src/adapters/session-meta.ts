/** Minimal shape needed to resolve the effective task id from session meta. */
interface TaskIdSource {
  taskId?: string;
  persistence?: { taskId?: string };
}

/**
 * The task id can arrive directly on the session meta or nested under
 * `persistence`; prefer the top-level value. Shared by the Claude and Codex
 * adapters so the fallback chain stays in sync.
 */
export function resolveTaskId(
  meta: TaskIdSource | undefined,
): string | undefined {
  return meta?.taskId ?? meta?.persistence?.taskId;
}

/** Minimal shape needed to resolve spoken narration from session meta. */
interface SpokenNarrationSource {
  spokenNarration?: boolean;
}

/**
 * Spoken narration is strictly opt-in: it is on only when a caller explicitly
 * sets `spokenNarration` true at session start. The desktop is the only client
 * that can play audio and the only place that knows the feature flag and the
 * user's setting, so it computes that boolean and passes it. Everything else
 * (headless cloud runs like Slack threads and Signals scouts, sandboxes, local
 * runs without the setting) stays silent, so the `speak` tool and its
 * instructions never load and never cost tokens where nothing is listening.
 * Shared by the Claude and Codex adapters.
 */
export function resolveSpokenNarration(
  meta: SpokenNarrationSource | undefined,
): boolean {
  return meta?.spokenNarration === true;
}

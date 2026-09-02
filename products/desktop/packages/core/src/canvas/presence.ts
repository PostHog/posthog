import type { Task, UserBasic } from "@posthog/shared/domain-types";

/**
 * How long an item counts as "someone is here right now". Within this window of
 * the last activity a face pulses. Kept short so a pulsing ring means work is
 * happening, not that it happened this morning.
 */
export const PRESENCE_LIVE_WINDOW_MS = 3 * 60_000;

/**
 * How long a (still) face lingers after the last activity. Presence here is
 * "recently active", so a face stays a while once its person steps away, then
 * fades — rather than blinking out the instant a run ends.
 */
export const PRESENCE_RECENT_WINDOW_MS = 2 * 60 * 60_000;

export type PresenceTier = "live" | "recent" | "idle";

export interface PresenceWindows {
  liveWindowMs?: number;
  recentWindowMs?: number;
}

/**
 * Where an item's last activity sits: `live` while it is happening, `recent`
 * for a while after, `idle` once it is old enough that a face would be noise.
 *
 * `ts` and `now` are epoch milliseconds. A `ts` in the future (clock skew)
 * reads as `live`.
 */
export function presenceTier(
  ts: number,
  now: number,
  {
    liveWindowMs = PRESENCE_LIVE_WINDOW_MS,
    recentWindowMs = PRESENCE_RECENT_WINDOW_MS,
  }: PresenceWindows = {},
): PresenceTier {
  const age = now - ts;
  if (age < liveWindowMs) return "live";
  if (age < recentWindowMs) return "recent";
  return "idle";
}

type ActivityTask = Pick<Task, "created_by" | "last_activity_at">;

/**
 * The uuids of the people whose latest activity in `tasks` is within the live
 * window — the faces that should pulse. Tasks with no author or an
 * unparseable timestamp are skipped.
 *
 * Callers pass the same recently-active people they already show (creator,
 * recent authors); this only decides which of those faces are working right
 * now, so the list of who appears never depends on the clock.
 */
export function liveUuidsFromTasks(
  tasks: readonly ActivityTask[],
  now: number,
  windows: PresenceWindows = {},
): ReadonlySet<string> {
  const live = new Set<string>();
  for (const task of tasks) {
    const author = task.created_by;
    if (!author || !task.last_activity_at) continue;
    const ts = Date.parse(task.last_activity_at);
    if (Number.isNaN(ts)) continue;
    if (presenceTier(ts, now, windows) === "live") live.add(author.uuid);
  }
  return live;
}

/** An empty presence result, shared so a quiet surface's props stay stable. */
export const NO_LIVE_UUIDS: ReadonlySet<string> = new Set<string>();

export type { UserBasic };

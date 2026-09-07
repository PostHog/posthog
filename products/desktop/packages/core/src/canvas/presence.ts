import type {
  ChannelRecentTaskAuthor,
  Task,
  UserBasic,
} from "@posthog/shared/domain-types";

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

export function shouldShowUserPresence(
  userUuid: string | null | undefined,
  currentUserUuid: string | null | undefined,
): boolean {
  return Boolean(userUuid && currentUserUuid && userUuid !== currentUserUuid);
}

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

/** Who is around in one channel: the recently-active people, and who's live. */
export interface ChannelPresence {
  /** Recently-active people, most-recent first, deduped, capped by `limit`. */
  people: UserBasic[];
  /** Of `people`, whoever is working right now. */
  liveUuids: ReadonlySet<string>;
}

interface PresenceByChannelOptions extends PresenceWindows {
  now: number;
  /** How many faces a channel keeps — the freshest, once sorted. */
  limit: number;
  currentUserUuid?: string;
}

/**
 * The recently-active people in each channel, keyed by channel id, built from
 * the server's recent-author response. A record with an unparseable timestamp
 * is skipped; a channel with nobody recent is absent from the map entirely.
 *
 * Tasks are sorted most-recent first here, so the result never depends on the
 * order the caller fetched them in.
 */
export function presenceByChannel(
  authors: readonly ChannelRecentTaskAuthor[],
  {
    now,
    limit,
    currentUserUuid,
    liveWindowMs,
    recentWindowMs,
  }: PresenceByChannelOptions,
): Map<string, ChannelPresence> {
  const dated = authors
    .map((author) => ({
      channel: author.channel_id,
      author: author.user,
      ts: Date.parse(author.last_activity_at),
    }))
    .filter(
      (t): t is { channel: string; author: UserBasic; ts: number } =>
        shouldShowUserPresence(t.author.uuid, currentUserUuid) &&
        !Number.isNaN(t.ts),
    )
    .sort((a, b) => b.ts - a.ts);

  const byChannel = new Map<
    string,
    { people: UserBasic[]; liveUuids: Set<string>; seen: Set<string> }
  >();
  for (const { channel, author, ts } of dated) {
    const tier = presenceTier(ts, now, { liveWindowMs, recentWindowMs });
    if (tier === "idle") continue;
    let entry = byChannel.get(channel);
    if (!entry) {
      entry = { people: [], liveUuids: new Set(), seen: new Set() };
      byChannel.set(channel, entry);
    }
    if (!entry.seen.has(author.uuid)) {
      if (entry.people.length >= limit) continue;
      entry.seen.add(author.uuid);
      entry.people.push(author);
    }
    // Only after the author is on the list, so a live mark never names a face
    // the cap dropped. The first record per author is their most recent.
    if (tier === "live") entry.liveUuids.add(author.uuid);
  }

  const result = new Map<string, ChannelPresence>();
  for (const [channel, entry] of byChannel) {
    result.set(channel, { people: entry.people, liveUuids: entry.liveUuids });
  }
  return result;
}

export type { UserBasic };

import {
  buildChannelItems,
  type ChannelItemModel,
} from "@posthog/core/canvas/channelItems";
import {
  type ChannelPresence,
  liveUuidsFromTasks,
  NO_LIVE_UUIDS,
  presenceByChannel,
  shouldShowUserPresence,
} from "@posthog/core/canvas/presence";
import type { Task, UserBasic } from "@posthog/shared/domain-types";
import { useArchivedTaskIds } from "@posthog/ui/features/archive/useArchivedTaskIds";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  AUTH_SCOPED_QUERY_META,
  useCurrentUser,
} from "@posthog/ui/features/auth/useCurrentUser";
import { useBlockedTaskIds } from "@posthog/ui/features/canvas/hooks/useBlockedSessionCount";
import {
  type TaskTimestamps,
  wantsAttention,
} from "@posthog/ui/features/canvas/hooks/useUnreadSessionCount";
import { usePinnedTasks } from "@posthog/ui/features/sidebar/usePinnedTasks";
import { useTaskViewed } from "@posthog/ui/features/sidebar/useTaskViewed";
import { useNow } from "@posthog/ui/hooks/useNow";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useRef } from "react";
import {
  SPACE_QUERY_GC_TIME_MS,
  SPACE_QUERY_STALE_TIME_MS,
} from "./spaceQueryPolicy";

/**
 * Its own key rather than the channel feed's: the tree asks for a short page,
 * and handing that truncated list to the space's own feed through a shared
 * cache would quietly cut it off at the same length. The root is exported so
 * task mutations (rename) can write through these pages the way they do the
 * feed's — a tree row polls too slowly to catch up on its own.
 */
export const spaceTreeTasksQueryRoot = ["space-tree-tasks"] as const;

const spaceTreeTasksQueryKey = (spaceId: string) =>
  [...spaceTreeTasksQueryRoot, spaceId] as const;

/** How many sessions a space shows when expanded in the list. */
const RECENT_TASKS_PER_SPACE = 5;

/**
 * A little more than the tree shows, because archived tasks are filtered out
 * client-side. Nothing like the feed's 500: a dozen open spaces would otherwise
 * pull thousands of full task records to draw sixty rows.
 */
const TREE_FETCH_LIMIT = 20;

/** One page of a space's sessions, with the total the page was cut from. */
export interface SpaceTaskPage {
  tasks: Task[];
  count: number;
}

const NO_PAGE: SpaceTaskPage = { tasks: [], count: 0 };

/**
 * One space's page, as every caller has to ask for it: the tree's `useQueries`,
 * the hover prefetch, and the space card. Same key and same `staleTime`, so a
 * warm cache is a no-op rather than a second request for the same rows.
 */
function spaceTaskPageQuery(
  client: ReturnType<typeof useOptionalAuthenticatedClient>,
  spaceId: string,
) {
  return {
    queryKey: spaceTreeTasksQueryKey(spaceId),
    queryFn: async (): Promise<SpaceTaskPage> => {
      if (!client) throw new Error("Not authenticated");
      return (await client.getTasksPage({
        channel: spaceId,
        limit: TREE_FETCH_LIMIT,
        // The tree shows a handful of rows out of a whole space, so which end the server cuts
        // the page from decides what can appear at all: by creation date, a session that has
        // been running since Monday is already off the page before this list sorts anything.
        ordering: "-last_activity_at",
      })) as SpaceTaskPage;
    },
    gcTime: SPACE_QUERY_GC_TIME_MS,
    meta: AUTH_SCOPED_QUERY_META,
    staleTime: SPACE_QUERY_STALE_TIME_MS,
  };
}

/** A space's rows: the most recently active few, and how many sessions it holds in all. */
export interface SpaceTasks {
  items: ChannelItemModel[];
  /** Everything in the space, not just the rows shown. */
  total: number;
}

/**
 * One object for every space with nothing to show, so a collapsed row's props
 * are identical between renders and its memo holds.
 */
export const NO_TASKS: SpaceTasks = { items: [], total: 0 };

/** What a space's rows were built from, so they can be reused unchanged. */
interface CachedSpaceTasks {
  page: SpaceTaskPage;
  archivedTaskIds: ReadonlySet<string>;
  pinnedTaskIds: ReadonlySet<string>;
  viewedAt: TaskTimestamps;
  blockedTaskIds: ReadonlySet<string>;
  built: SpaceTasks;
}

/**
 * What a session is asking of you: blocked on you, then unread or working,
 * then quiet.
 *
 * Blue is its own tier rather than part of the yellow one, because the two are
 * cleared differently. `wantsAttention` is the space dot's yellow predicate.
 * Opening clears unread; live work stays yellow until it settles. A permission
 * prompt only goes away when answered, so a blue row holds its place until it is.
 */
const ATTENTION_TIERS = 3;

function attentionTier(
  item: ChannelItemModel,
  viewedAt: TaskTimestamps,
  blockedTaskIds: ReadonlySet<string>,
): number {
  if (item.task && blockedTaskIds.has(item.task.id)) return 0;
  if (item.task && wantsAttention(item.task, viewedAt)) return 1;
  return 2;
}

/**
 * The order a space's rows are cut to five in: pinned sessions, then the rest,
 * each run ordered by what it wants from you and still newest-activity first
 * inside that.
 *
 * Two keys rather than one, because they answer different questions. Pinning is
 * the reader's own filing and outranks everything, the way it does in the Code
 * sidebar's list. Within a run, a space that shows a dot has to show the row
 * behind it: by recency alone the session its dot is counting can sit below the
 * cut, leaving a marked space that opens onto five quiet rows.
 *
 * Buckets rather than a comparator: the page arrives newest-activity first, and
 * pushing in order keeps that inside each run without a second sort key.
 */
function spaceTreeOrder(
  items: ChannelItemModel[],
  viewedAt: TaskTimestamps,
  blockedTaskIds: ReadonlySet<string>,
): ChannelItemModel[] {
  const runs: ChannelItemModel[][] = [[], [], [], [], [], []];
  for (const item of items) {
    const tier = attentionTier(item, viewedAt, blockedTaskIds);
    runs[(item.pinned ? 0 : ATTENTION_TIERS) + tier]?.push(item);
  }
  return runs.flat();
}

/**
 * Module-level so `useQueries` can memoize on it: an inline combine is a new
 * function every render, which makes every render rebuild the lists — and with
 * them the item models and every row's props.
 */
function combineTaskPages(
  queries: { data?: SpaceTaskPage }[],
): SpaceTaskPage[] {
  return queries.map((query) => query.data ?? NO_PAGE);
}

// Slower than the open channel's own feed (5s): the tree is a glance at what's
// been happening, not the surface you watch a run on, and every expanded space
// pays this interval.
const SPACE_TREE_POLL_INTERVAL_MS = 30_000;

/**
 * The most recently active sessions in each of the given spaces, keyed by space id, as the
 * same item model the space's own session list is built from — so a tree row
 * can wear the status dot and badges those rows do.
 *
 * One query per space, and only for the spaces actually expanded. The flat task
 * list can't stand in for this: it is capped, and most of its rows carry no
 * channel at all.
 */
export function useRecentSpaceTasks(
  spaceIds: string[],
): Map<string, SpaceTasks> {
  const client = useOptionalAuthenticatedClient();
  const archivedTaskIds = useArchivedTaskIds();
  const { pinnedTaskIds } = usePinnedTasks();
  const { timestamps: viewedAt } = useTaskViewed();
  const blockedTaskIds = useBlockedTaskIds();

  const pagePerSpace = useQueries({
    queries: spaceIds.map((spaceId) => ({
      ...spaceTaskPageQuery(client, spaceId),
      enabled: !!client,
      refetchInterval: SPACE_TREE_POLL_INTERVAL_MS,
    })),
    combine: combineTaskPages,
  });

  // Per-space memo, not one over the whole map: opening another space changes
  // the id list, and rebuilding every space's items from that would hand each
  // already-open row a new array — enough to re-render every session row in the
  // tree on every expand.
  const cache = useRef(new Map<string, CachedSpaceTasks>());

  return useMemo(() => {
    const bySpace = new Map<string, SpaceTasks>();
    spaceIds.forEach((spaceId, index) => {
      const page = pagePerSpace[index] ?? NO_PAGE;
      const cached = cache.current.get(spaceId);
      if (
        cached &&
        cached.page === page &&
        cached.archivedTaskIds === archivedTaskIds &&
        cached.pinnedTaskIds === pinnedTaskIds &&
        cached.viewedAt === viewedAt &&
        cached.blockedTaskIds === blockedTaskIds
      ) {
        bySpace.set(spaceId, cached.built);
        return;
      }
      // Canvases are the space's own list to show; the tree answers "what has
      // been running here lately".
      const available = buildChannelItems({
        dashboards: [],
        feedTasks: page.tasks,
        archivedTaskIds,
        pinnedTaskIds,
        ownedBy: null,
      });
      // A page that came back short is the whole space, so the count is exact
      // once the archived ones are dropped. A full page falls back to the
      // server's total, which excludes archived tasks — bar any this device has
      // archived and not yet mirrored, which `useServerArchiveSync` is working
      // through.
      const built: SpaceTasks = {
        items: spaceTreeOrder(available, viewedAt, blockedTaskIds).slice(
          0,
          RECENT_TASKS_PER_SPACE,
        ),
        total:
          page.tasks.length < TREE_FETCH_LIMIT ? available.length : page.count,
      };
      cache.current.set(spaceId, {
        page,
        archivedTaskIds,
        pinnedTaskIds,
        viewedAt,
        blockedTaskIds,
        built,
      });
      bySpace.set(spaceId, built);
    });
    return bySpace;
  }, [
    spaceIds,
    pagePerSpace,
    archivedTaskIds,
    pinnedTaskIds,
    viewedAt,
    blockedTaskIds,
  ]);
}

/**
 * Warm a space's sessions before it is expanded — from the row's hover, the way
 * the channel pane's own queries are warmed. A cold expand pays a round trip
 * (over a second on a slow one); a warm one renders from cache.
 */
export function usePrefetchSpaceTasks(): (spaceId: string) => void {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();

  return useCallback(
    (spaceId: string) => {
      if (!client) return;
      void queryClient.prefetchQuery(spaceTaskPageQuery(client, spaceId));
    },
    [client, queryClient],
  );
}

/** What a space's card says about it beyond the counts its row already has. */
export interface SpaceOverview {
  /** Who has been working here, creator first. Capped by `peopleLimit`. */
  people: UserBasic[];
  /** Of `people`, whoever is working right now — their faces pulse. */
  liveUuids: ReadonlySet<string>;
  /**
   * Sessions in the space, by the same reckoning the tree's total uses, or
   * `null` until the page arrives — a space's count is not zero just because
   * nothing has been fetched yet.
   */
  total: number | null;
}

const NO_OVERVIEW: SpaceOverview = {
  people: [],
  liveUuids: NO_LIVE_UUIDS,
  total: null,
};

/**
 * A space's people and its session count, off the same page the tree draws its
 * rows from — which the row's own hover has already warmed by the time a card
 * opens over it, so this costs no request of its own.
 *
 * The people are who has been working here, not a membership list: the backend
 * has no such list, and the page is the `TREE_FETCH_LIMIT` most recently
 * active sessions rather than the space's whole history.
 *
 * The creator leads, whether or not they appear in that page. They are the one
 * name the space itself carries, and a group that opened with whoever happened
 * to run the last session read as if the space belonged to them.
 */
export function useSpaceOverview(
  spaceId: string,
  createdBy: UserBasic | null,
  peopleLimit: number,
): SpaceOverview {
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const currentUserUuid = currentUser?.uuid;
  const archivedTaskIds = useArchivedTaskIds();
  const { data } = useQuery({
    ...spaceTaskPageQuery(client, spaceId),
    enabled: !!client,
  });
  // A dependency, not `Date.now()` inline: the query keeps `data` referentially
  // equal across polls that return the same rows, so without the clock in the
  // memo a live dot would never fade while nobody touched the space.
  const now = useNow();

  return useMemo(() => {
    if (!data) return NO_OVERVIEW;
    const live = data.tasks.filter((task) => !archivedTaskIds.has(task.id));
    return {
      people: currentUserUuid
        ? spacePeople(live, createdBy, peopleLimit, currentUserUuid)
        : [],
      liveUuids: currentUserUuid
        ? liveUuidsFromTasks(live, now)
        : NO_LIVE_UUIDS,
      // A page that came back short is the whole space, so the count is exact
      // once the archived ones are dropped. A full page falls back to the
      // server's total, which excludes archived tasks — bar any this device has
      // archived and not yet mirrored.
      total: data.tasks.length < TREE_FETCH_LIMIT ? live.length : data.count,
    };
  }, [data, archivedTaskIds, createdBy, peopleLimit, currentUserUuid, now]);
}

/**
 * The space's faces, in the order the group stacks them: the creator, then
 * whoever ran the sessions, most recently active first, each person once and no more than
 * `limit` of them.
 *
 * The creator leads whether or not they ran anything, and is not counted twice
 * when they did — the leading avatar is the one that wears the crown, so its
 * place is what makes the crown mean "created this".
 */
export function spacePeople(
  tasks: Pick<Task, "created_by">[],
  createdBy: UserBasic | null,
  limit: number,
  currentUserUuid?: string,
): UserBasic[] {
  const people: UserBasic[] = [];
  const seen = new Set<string>();
  const add = (user: UserBasic | null | undefined) => {
    if (
      !user ||
      !shouldShowUserPresence(user.uuid, currentUserUuid) ||
      seen.has(user.uuid) ||
      people.length >= limit
    )
      return;
    seen.add(user.uuid);
    people.push(user);
  };
  add(createdBy);
  for (const task of tasks) add(task.created_by);
  return people;
}

/** Faces a collapsed space row shows — kept small so the row stays a glance. */
const SPACE_PRESENCE_LIMIT = 3;
/**
 * One page of the team's most recently active tasks across every space, which
 * the whole list's presence is aggregated from. Full task records are heavy, so
 * this is a short page polled slowly — presence here is "recently active", not
 * a live cursor, so a minute of lag is invisible.
 *
 * The page is a global cut, so it is also a bound on what can show: a space
 * whose newest activity sits below this many newer tasks elsewhere shows no
 * faces even inside the recent window. The task list has no date filter to ask
 * for "the last two hours" instead, so the fix for a team that outruns this is a
 * slim per-channel participants field on the server, not a bigger page here.
 */
const SPACE_PRESENCE_FETCH_LIMIT = 100;
const SPACE_PRESENCE_POLL_INTERVAL_MS = 90_000;

const NO_PRESENCE: ReadonlyMap<string, ChannelPresence> = new Map();

/** Whether two channels' presence draw the same, so a row can reuse the old object. */
function samePresence(a: ChannelPresence, b: ChannelPresence): boolean {
  if (a.people.length !== b.people.length) return false;
  if (a.liveUuids.size !== b.liveUuids.size) return false;
  for (let index = 0; index < a.people.length; index++) {
    if (a.people[index]?.uuid !== b.people[index]?.uuid) return false;
  }
  for (const uuid of a.liveUuids) if (!b.liveUuids.has(uuid)) return false;
  return true;
}

/**
 * Who is recently active in each space, keyed by space id — the faces a
 * collapsed space row wears without expanding it. One project-wide query feeds
 * the whole list, rather than one per space.
 *
 * Each channel's entry keeps its object identity across polls while its faces
 * don't change, so a memoized space row only re-renders when its own presence
 * does.
 */
export function useSpacePresence(): ReadonlyMap<string, ChannelPresence> {
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const currentUserUuid = currentUser?.uuid;
  const archivedTaskIds = useArchivedTaskIds();
  const { data } = useQuery({
    queryKey: ["space-presence"],
    queryFn: async (): Promise<SpaceTaskPage> => {
      if (!client) throw new Error("Not authenticated");
      return (await client.getTasksPage({
        limit: SPACE_PRESENCE_FETCH_LIMIT,
        ordering: "-last_activity_at",
      })) as SpaceTaskPage;
    },
    enabled: !!client,
    refetchInterval: SPACE_PRESENCE_POLL_INTERVAL_MS,
    gcTime: SPACE_QUERY_GC_TIME_MS,
    meta: AUTH_SCOPED_QUERY_META,
    staleTime: SPACE_QUERY_STALE_TIME_MS,
  });

  // In the memo for the same reason `useSpaceOverview` has it: the tiers are
  // clock-derived, and the query alone would never move them.
  const now = useNow();

  // The last object handed out per channel, so a row can be given the same one
  // back. Entries are set in place rather than the map swapped, as the sibling
  // cache above does; a channel that leaves the page keeps a stale entry until
  // it returns, which costs one small object per space ever seen.
  const cache = useRef(new Map<string, ChannelPresence>());
  return useMemo(() => {
    if (!data || !currentUserUuid) return NO_PRESENCE;
    const live = data.tasks.filter((task) => !archivedTaskIds.has(task.id));
    const fresh = presenceByChannel(live, {
      now,
      limit: SPACE_PRESENCE_LIMIT,
      currentUserUuid,
    });
    const stable = new Map<string, ChannelPresence>();
    for (const [channelId, next] of fresh) {
      const prev = cache.current.get(channelId);
      const kept = prev && samePresence(prev, next) ? prev : next;
      cache.current.set(channelId, kept);
      stable.set(channelId, kept);
    }
    return stable;
  }, [data, archivedTaskIds, currentUserUuid, now]);
}

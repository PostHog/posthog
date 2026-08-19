import {
  formatShortDayLabel,
  getLocalDayKey,
  type WorkspaceMode,
} from "@posthog/shared";
import type {
  Task,
  TaskRunStatus,
  UserBasic,
} from "@posthog/shared/domain-types";
import { isTaskUnread, type TaskTimestamp } from "../sidebar/buildSidebarData";
import { taskActivityAt, taskActivityTimestamp } from "../tasks/taskActivity";
import type { DashboardRecord } from "./dashboardSchemas";

/** Where a session runs. `worktree` is a local checkout, so it reads as local. */
export type ChannelItemEnvironment = "local" | "cloud";

export interface ChannelItemModel {
  key: string;
  kind: "task" | "canvas";
  id: string;
  title: string;
  /** Activity time for the activity-first sort: a session's `last_activity_at`, or a canvas's `updatedAt`. */
  ts: number;
  /** When it was first made, for the created-first sort. */
  createdAt: number;
  pinned: boolean;
  rawStatus: TaskRunStatus | null;
  /**
   * The three session facts the filters ask about. A canvas has no run, so it
   * carries the empty answer to all three and drops out of any filter that
   * names one.
   */
  environment: ChannelItemEnvironment | null;
  /** The product that filed it (`origin_product`), or null if it started here. */
  source: string | null;
  sourceResourceId?: string | null;
  /** The agent is blocked on an answer from you. */
  needsInput: boolean;
  /** There is activity here you haven't seen. */
  unread: boolean;
  authorUser: UserBasic | null;
  authorName: string | null;
  authorUuid: string | null;
  templateId: string | null;
  /**
   * The source task record for `kind: "task"` rows, `null` for canvases. Rows
   * need the whole task, not a projection of it: the status dot is derived from
   * session/workspace/viewed state that only the renderer holds, and the hooks
   * that supply it (`useChannelTaskData`, `useTaskPrStatus`) take a `Task`.
   * Carrying the reference here keeps that a lookup the list already did rather
   * than a second pass over every row.
   */
  task: Task | null;
}

export interface ChannelItemOwner {
  uuid: string | null;
}

// Ownership is decided solely by the stable creator uuid (canvases via
// `createdByUuid`, tasks via `created_by.uuid` — both set in buildChannelItems).
// A display name is NOT an identity — two users can share one — so it must never
// gate the private `#me` space. Items without a creator uuid fail closed
// (excluded from #me); `authorName`/`authorUser` are display-only.
function isOwnedBy(
  item: Pick<ChannelItemModel, "authorUuid">,
  owner: ChannelItemOwner,
): boolean {
  return item.authorUuid != null && item.authorUuid === owner.uuid;
}

/**
 * The per-session state the item list can't read off a task on its own: what the
 * live session is asking for, when you last looked, and where the session's
 * workspace actually is. All three live in the renderer, so they are handed in
 * rather than fetched — and each one defaults to "nothing known", which reads as
 * a quiet, unplaced session rather than a wrong claim about one.
 */
export interface ChannelSessionFacts {
  needsInputTaskIds: ReadonlySet<string>;
  viewedTimestamps: Readonly<Record<string, TaskTimestamp>>;
  workspaceModeByTaskId: ReadonlyMap<string, WorkspaceMode>;
}

const NO_SESSION_FACTS: ChannelSessionFacts = {
  needsInputTaskIds: new Set(),
  viewedTimestamps: {},
  workspaceModeByTaskId: new Map(),
};

/**
 * Where a session runs, preferring the workspace we can see over the run's own
 * claim — the same precedence `deriveTaskData` uses, so a row and this filter
 * can't disagree. A session with neither is unplaced, not local.
 */
function environmentOf(
  task: Task,
  workspaceMode: WorkspaceMode | undefined,
): ChannelItemEnvironment | null {
  const mode = workspaceMode ?? task.latest_run?.environment ?? null;
  if (mode === null) return null;
  return mode === "cloud" ? "cloud" : "local";
}

/**
 * `origin_product` for a session someone started here rather than one filed by
 * another product. It is the default the backend stamps on, so it is an absence
 * of a source, not one of the sources to choose between.
 */
const SELF_ORIGIN = "user_created";

function sourceOf(task: Task): string | null {
  const origin = task.origin_product;
  return origin && origin !== SELF_ORIGIN ? origin : null;
}

export function buildChannelItems({
  dashboards,
  feedTasks,
  archivedTaskIds,
  pinnedTaskIds,
  ownedBy,
  sessionFacts = NO_SESSION_FACTS,
}: {
  dashboards: readonly DashboardRecord[];
  feedTasks: readonly Task[];
  archivedTaskIds: ReadonlySet<string>;
  pinnedTaskIds: ReadonlySet<string>;
  ownedBy: ChannelItemOwner | null;
  sessionFacts?: ChannelSessionFacts;
}): ChannelItemModel[] {
  const canvasItems: ChannelItemModel[] = dashboards.map((d) => ({
    key: `canvas:${d.id}`,
    kind: "canvas",
    id: d.id,
    title: d.name,
    ts: d.updatedAt,
    createdAt: d.createdAt,
    pinned: d.pinnedAt != null,
    rawStatus: null,
    environment: null,
    source: d.sourceProduct,
    sourceResourceId: d.sourceResourceId ?? null,
    needsInput: false,
    unread: false,
    authorUser: null,
    authorName: d.createdBy ?? null,
    authorUuid: d.createdByUuid ?? null,
    templateId: d.templateId,
    task: null,
  }));

  const taskItems: ChannelItemModel[] = feedTasks.flatMap((task) =>
    archivedTaskIds.has(task.id)
      ? []
      : [
          {
            key: `task:${task.id}`,
            kind: "task" as const,
            id: task.id,
            title: task.title || "Untitled task",
            ts: taskActivityTimestamp(task, "updated") || 0,
            createdAt: Date.parse(task.created_at) || 0,
            pinned: pinnedTaskIds.has(task.id),
            rawStatus: task.latest_run?.status ?? null,
            environment: environmentOf(
              task,
              sessionFacts.workspaceModeByTaskId.get(task.id),
            ),
            source: sourceOf(task),
            sourceResourceId: task.signal_report ?? null,
            needsInput: sessionFacts.needsInputTaskIds.has(task.id),
            unread: isTaskUnread(
              taskActivityAt(task),
              sessionFacts.viewedTimestamps[task.id],
            ),
            authorUser: task.created_by ?? null,
            authorName: null,
            authorUuid: task.created_by?.uuid ?? null,
            templateId: null,
            task,
          },
        ],
  );

  const all = [...canvasItems, ...taskItems].sort((a, b) => b.ts - a.ts);
  return ownedBy ? all.filter((item) => isOwnedBy(item, ownedBy)) : all;
}

export type CreatedByFilter = "anyone" | "me" | "others";
/** What a session wants from you, in the row dot's vocabulary. */
export type AttentionFilter = "any" | "needs_input" | "unread";
export type PinnedFilter = "any" | "pinned";
export type EnvironmentFilter = "any" | ChannelItemEnvironment;
/** `ANY_SOURCE`, or an `origin_product` key like `slack`. */
export type SourceFilter = string;
export type ChannelItemSort = "recent" | "created" | "alpha";

export const ANY_SOURCE = "any";

export interface ChannelItemFilters {
  createdBy: CreatedByFilter;
  attention: AttentionFilter;
  pinned: PinnedFilter;
  environment: EnvironmentFilter;
  source: SourceFilter;
}

export const DEFAULT_CHANNEL_ITEM_FILTERS: ChannelItemFilters = {
  createdBy: "anyone",
  attention: "any",
  pinned: "any",
  environment: "any",
  source: ANY_SOURCE,
};

/** Newest activity first, which is what a session list is for. */
export const DEFAULT_CHANNEL_ITEM_SORT: ChannelItemSort = "recent";

/**
 * Whether the list is narrowed — what lights the filter button up. The search
 * box is excluded: it says so itself, visibly, while a filter left on in a
 * closed menu is the state nothing else on screen explains.
 */
export function hasActiveChannelItemFilters(
  filters: ChannelItemFilters,
): boolean {
  return (
    filters.createdBy !== "anyone" ||
    filters.attention !== "any" ||
    filters.pinned !== "any" ||
    filters.environment !== "any" ||
    filters.source !== ANY_SOURCE
  );
}

/**
 * The sources present in a list, so the menu only offers the ones that can
 * actually match. Keyed by `origin_product`; sorted so the menu is stable
 * between renders.
 */
export function channelItemSources(
  items: readonly ChannelItemModel[],
): string[] {
  const sources = new Set<string>();
  for (const item of items) {
    if (item.source) sources.add(item.source);
  }
  return [...sources].sort();
}

export function filterChannelItems(
  items: readonly ChannelItemModel[],
  {
    query,
    filters,
    me,
  }: {
    query: string;
    filters: ChannelItemFilters;
    me: ChannelItemOwner;
  },
): ChannelItemModel[] {
  const normalizedQuery = query.trim().toLowerCase();
  return items.filter((item) => {
    if (
      normalizedQuery &&
      !item.title.toLowerCase().includes(normalizedQuery)
    ) {
      return false;
    }
    if (filters.createdBy !== "anyone") {
      // An item with no creator uuid (e.g. the backend returns `created_by:
      // null` once a creator is deleted) belongs to neither bucket: it isn't
      // mine, but "others" means a *known* other person, not "unknown".
      if (item.authorUuid == null) return false;
      const mine = isOwnedBy(item, me);
      if (filters.createdBy === "me" ? !mine : mine) return false;
    }
    if (filters.attention === "needs_input" && !item.needsInput) return false;
    if (filters.attention === "unread" && !item.unread) return false;
    if (filters.pinned === "pinned" && !item.pinned) return false;
    // An unplaced session (no workspace, no run) matches neither environment:
    // naming one is a question about where the work happens, and "we don't
    // know" is not an answer to it.
    if (
      filters.environment !== "any" &&
      item.environment !== filters.environment
    ) {
      return false;
    }
    if (filters.source !== ANY_SOURCE && item.source !== filters.source) {
      return false;
    }
    return true;
  });
}

function compareChannelItems(
  a: ChannelItemModel,
  b: ChannelItemModel,
  sort: ChannelItemSort,
): number {
  if (sort === "alpha") return a.title.localeCompare(b.title);
  if (sort === "created") return b.createdAt - a.createdAt;
  return b.ts - a.ts;
}

/**
 * The list in the order the reader asked for, pins first.
 *
 * Pins lead whatever the sort is: a pin is a request not to lose the thing, and
 * below the sort it would fall off the end of the list's cap. The order inside
 * each half is the one that was chosen.
 */
export function sortChannelItems(
  items: readonly ChannelItemModel[],
  sort: ChannelItemSort,
): ChannelItemModel[] {
  const pinned = items.filter((item) => item.pinned);
  const rest = items.filter((item) => !item.pinned);
  return [
    ...pinned.sort((a, b) => compareChannelItems(a, b, sort)),
    ...rest.sort((a, b) => compareChannelItems(a, b, sort)),
  ];
}

export interface ChannelItemSection {
  /** Stable between renders, so a section isn't rebuilt on every poll. */
  key: string;
  /** Null where the run has nothing to be called — an alphabetical list. */
  label: string | null;
  items: ChannelItemModel[];
}

/** The section pinned sessions lead the list under. */
export const PINNED_SECTION_KEY = "pinned";

/**
 * A sorted list cut into the sections a reader can scan: the pins, then one per
 * calendar day.
 *
 * The day is read off whichever timestamp the sort ordered by, so each section
 * is a contiguous run — dating a created-first list by last activity would
 * reopen a day the list had already passed. Alphabetical order holds no days at
 * all, so it stays one unnamed run below the pins.
 *
 * Takes the list `sortChannelItems` returned: pins already lead it, so lifting
 * them out keeps the order they were given.
 */
export function groupChannelItems(
  items: readonly ChannelItemModel[],
  sort: ChannelItemSort,
  now: Date = new Date(),
): ChannelItemSection[] {
  const sections: ChannelItemSection[] = [];

  const pinned = items.filter((item) => item.pinned);
  if (pinned.length > 0) {
    sections.push({ key: PINNED_SECTION_KEY, label: "Pinned", items: pinned });
  }

  const rest = items.filter((item) => !item.pinned);
  if (rest.length === 0) return sections;
  if (sort === "alpha") {
    sections.push({ key: "all", label: null, items: rest });
    return sections;
  }

  for (const item of rest) {
    // Clamped to now, because the label does the same: a row stamped in the
    // future (clock skew between the writer and this client) would otherwise
    // take a day key of its own under a second "Today" header.
    const ts = Math.min(sort === "created" ? item.createdAt : item.ts, +now);
    const key = `day:${getLocalDayKey(ts)}`;
    const open = sections[sections.length - 1];
    if (open?.key === key) {
      open.items.push(item);
      continue;
    }
    sections.push({ key, label: formatShortDayLabel(ts, now), items: [item] });
  }
  return sections;
}

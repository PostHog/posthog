import type {
  Task,
  TaskRunStatus,
  UserBasic,
} from "@posthog/shared/domain-types";
import type { DashboardSummary } from "./dashboardSchemas";

export interface ChannelItemModel {
  key: string;
  kind: "task" | "canvas";
  id: string;
  title: string;
  ts: number;
  pinned: boolean;
  rawStatus: TaskRunStatus | null;
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

export function buildChannelItems({
  dashboards,
  feedTasks,
  archivedTaskIds,
  pinnedTaskIds,
  ownedBy,
}: {
  dashboards: readonly DashboardSummary[];
  feedTasks: readonly Task[];
  archivedTaskIds: ReadonlySet<string>;
  pinnedTaskIds: ReadonlySet<string>;
  ownedBy: ChannelItemOwner | null;
}): ChannelItemModel[] {
  const canvasItems: ChannelItemModel[] = dashboards.map((d) => ({
    key: `canvas:${d.id}`,
    kind: "canvas",
    id: d.id,
    title: d.name,
    ts: d.updatedAt,
    pinned: d.pinnedAt != null,
    rawStatus: null,
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
            ts: Date.parse(task.updated_at) || 0,
            pinned: pinnedTaskIds.has(task.id),
            rawStatus: task.latest_run?.status ?? null,
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

export function filterChannelItems(
  items: readonly ChannelItemModel[],
  {
    query,
    createdBy,
    status,
    me,
  }: {
    query: string;
    createdBy: CreatedByFilter;
    status: TaskRunStatus | null;
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
    if (createdBy !== "anyone") {
      // An item with no creator uuid (e.g. the backend returns `created_by:
      // null` once a creator is deleted) belongs to neither bucket: it isn't
      // mine, but "others" means a *known* other person, not "unknown".
      if (item.authorUuid == null) return false;
      const mine = isOwnedBy(item, me);
      if (createdBy === "me" ? !mine : mine) return false;
    }
    if (status && item.rawStatus !== status) return false;
    return true;
  });
}

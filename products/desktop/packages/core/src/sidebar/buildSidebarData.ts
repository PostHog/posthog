import { readPrUrls, type WorkspaceMode } from "@posthog/shared";
import type { Task, TaskRunStatus } from "@posthog/shared/domain-types";
import { getRepositoryInfo } from "./groupTasks";
import type { TaskData, TaskGroup } from "./sidebarData.types";

export type SortMode = "updated" | "created";
export type OrganizeMode = "by-project" | "chronological";

export interface FullTask {
  id: string;
  title: string;
  repository?: string | null;
  created_at: string;
  updated_at: string;
  origin_product?: string;
  latest_run?: {
    status?: TaskRunStatus | null;
    environment?: "local" | "cloud" | null;
    output?: { pr_url?: unknown } | null;
    state?: Record<string, unknown> | null;
  } | null;
}

export interface SidebarTask {
  id: string;
  title: string;
  repository?: string | null;
  created_at: string;
  updated_at: string;
  origin_product?: string;
  slack_thread_url?: string;
  latest_run?: {
    status?: TaskRunStatus | null;
    environment?: "local" | "cloud" | null;
    output?: { pr_url?: unknown } | null;
  } | null;
}

// Accepts both the local `FullTask` shape and the canonical `Task` from
// `@posthog/shared` so callers holding a real `Task` can narrow it directly,
// without an `as unknown as FullTask` escape hatch.
export function narrowFullTask(task: FullTask | Task): SidebarTask {
  const slackThreadUrl = task.latest_run?.state?.slack_thread_url;
  return {
    id: task.id,
    title: task.title,
    repository: task.repository ?? null,
    created_at: task.created_at,
    updated_at: task.updated_at,
    latest_run: task.latest_run
      ? {
          status: task.latest_run.status,
          environment: task.latest_run.environment ?? null,
          output: task.latest_run.output ?? null,
        }
      : null,
    origin_product: task.origin_product,
    slack_thread_url:
      typeof slackThreadUrl === "string" ? slackThreadUrl : undefined,
  };
}

export interface FilterVisibleOptions {
  archivedIds: ReadonlySet<string>;
  workspaceIds: ReadonlySet<string>;
  provisioningIds: ReadonlySet<string>;
  showAllUsers: boolean;
  showInternal: boolean;
}

export function filterVisibleTasks(
  rawTasks: SidebarTask[],
  options: FilterVisibleOptions,
): SidebarTask[] {
  return rawTasks.filter(
    (task) =>
      !options.archivedIds.has(task.id) &&
      (options.showAllUsers ||
        options.showInternal ||
        options.workspaceIds.has(task.id) ||
        options.provisioningIds.has(task.id)),
  );
}

export interface TaskSession {
  isPromptPending?: boolean;
  pendingPermissions?: { size: number };
  cloudStatus?: TaskRunStatus;
  cloudOutput?: { pr_url?: unknown } | null;
}

/**
 * A primitive signature of just the session fields the sidebar renders (see
 * {@link deriveTaskData}). The sidebar subscribes to this instead of the whole
 * sessions record, so it doesn't rebuild on every streamed event — only when a
 * field it actually reads changes. It deliberately ignores `events`.
 */
export function computeSidebarSessionSignature(
  sessions: Record<string, TaskSession & { taskId?: string }>,
): string {
  let signature = "";
  for (const session of Object.values(sessions)) {
    if (!session.taskId) continue;
    const prUrl =
      typeof session.cloudOutput?.pr_url === "string"
        ? session.cloudOutput.pr_url
        : "";
    signature += `${session.taskId}:${session.isPromptPending ? 1 : 0}:${
      session.pendingPermissions?.size ?? 0
    }:${session.cloudStatus ?? ""}:${prUrl};`;
  }
  return signature;
}

export interface TaskWorkspace {
  folderId?: string | null;
  folderPath?: string | null;
  branchName?: string | null;
  linkedBranch?: string | null;
  mode?: WorkspaceMode;
}

export interface TaskTimestamp {
  lastViewedAt?: number | null;
  lastActivityAt?: number | null;
}

export interface DeriveTaskDataContext {
  session: TaskSession | undefined;
  workspace: TaskWorkspace | undefined;
  timestamp: TaskTimestamp | undefined;
  pinnedIds: ReadonlySet<string>;
  suspendedIds: ReadonlySet<string>;
  slackTaskIds: ReadonlySet<string>;
  slackThreadUrlByTaskId: ReadonlyMap<string, string>;
}

export function deriveTaskData(
  task: SidebarTask,
  ctx: DeriveTaskDataContext,
): TaskData {
  const { session, workspace, timestamp } = ctx;
  const apiUpdatedAt = new Date(task.updated_at).getTime();
  const localActivity = timestamp?.lastActivityAt;
  const lastActivityAt = localActivity
    ? Math.max(apiUpdatedAt, localActivity)
    : apiUpdatedAt;
  const createdAt = new Date(task.created_at).getTime();

  const taskLastViewedAt = timestamp?.lastViewedAt;
  const isUnread =
    taskLastViewedAt != null && lastActivityAt > taskLastViewedAt;

  const cloudPrUrl =
    readPrUrls(task.latest_run?.output)[0] ??
    readPrUrls(session?.cloudOutput)[0] ??
    null;

  const originProduct =
    task.origin_product ??
    (ctx.slackTaskIds.has(task.id) ? "slack" : undefined);
  const slackThreadUrl =
    task.slack_thread_url ?? ctx.slackThreadUrlByTaskId.get(task.id);

  return {
    id: task.id,
    title: task.title,
    createdAt,
    lastActivityAt,
    isGenerating: session?.isPromptPending ?? false,
    isUnread,
    isPinned: ctx.pinnedIds.has(task.id),
    isSuspended: ctx.suspendedIds.has(task.id),
    needsPermission: (session?.pendingPermissions?.size ?? 0) > 0,
    repository: getRepositoryInfo(task, workspace?.folderPath ?? undefined),
    folderId: workspace?.folderId || undefined,
    taskRunStatus: session?.cloudStatus ?? task.latest_run?.status ?? undefined,
    taskRunEnvironment: task.latest_run?.environment ?? undefined,
    // The `latest_run` fallback only matters in the `showAllUsers` view: the
    // default view's `filterVisibleTasks` already restricts to tasks with a
    // local `workspace`, so a pure-cloud task without one only shows up there.
    workspaceMode:
      workspace?.mode ??
      (task.latest_run?.environment === "cloud" ? "cloud" : undefined),
    originProduct,
    slackThreadUrl,
    folderPath: workspace?.folderPath ?? null,
    cloudPrUrl,
    branchName: workspace?.branchName ?? null,
    linkedBranch: workspace?.linkedBranch ?? null,
  };
}

// A Record keyed by the full `WorkspaceMode` union, so adding a mode to the
// schema forces a compile error here instead of silently falling out of sync
// with `ALL_WORKSPACE_MODES` (and the filter's "all enabled" short-circuit).
const WORKSPACE_MODE_MEMBERSHIP: Record<WorkspaceMode, true> = {
  worktree: true,
  local: true,
  cloud: true,
};

export const ALL_WORKSPACE_MODES: readonly WorkspaceMode[] = Object.keys(
  WORKSPACE_MODE_MEMBERSHIP,
) as WorkspaceMode[];

/**
 * Keeps tasks whose workspace mode is in `enabledModes`. Tasks without a known
 * mode always pass so an unclassified task never silently disappears.
 */
export function filterByWorkspaceMode(
  tasks: TaskData[],
  enabledModes: readonly WorkspaceMode[],
): TaskData[] {
  if (enabledModes.length >= ALL_WORKSPACE_MODES.length) return tasks;
  return tasks.filter(
    (task) =>
      task.workspaceMode == null || enabledModes.includes(task.workspaceMode),
  );
}

function getSortValue(task: TaskData, sortMode: SortMode): number {
  return sortMode === "updated" ? task.lastActivityAt : task.createdAt;
}

function sortTasks(tasks: TaskData[], sortMode: SortMode): TaskData[] {
  return [...tasks].sort(
    (a, b) => getSortValue(b, sortMode) - getSortValue(a, sortMode),
  );
}

export interface PartitionedTasks {
  pinnedTasks: TaskData[];
  sortedUnpinnedTasks: TaskData[];
  totalCount: number;
}

export function partitionAndSortTasks(
  taskData: TaskData[],
  sortMode: SortMode,
): PartitionedTasks {
  const pinned: TaskData[] = [];
  const unpinned: TaskData[] = [];
  for (const task of taskData) {
    if (task.isPinned) {
      pinned.push(task);
    } else {
      unpinned.push(task);
    }
  }
  return {
    pinnedTasks: sortTasks(pinned, sortMode),
    sortedUnpinnedTasks: sortTasks(unpinned, sortMode),
    totalCount: unpinned.length,
  };
}

export interface VisibleTasksSlice {
  flatTasks: TaskData[];
  hasMore: boolean;
}

/**
 * Caps the flat (chronological) task list to the current history window. The
 * cap is a render bound, not a cosmetic one: every rendered task row mounts its
 * own workspace and PR-status queries, so an uncapped list of thousands of
 * tasks fires thousands of per-row requests and floods the DOM. Pinned tasks
 * are rendered separately and are never capped.
 */
export function sliceVisibleTasks(
  sortedUnpinnedTasks: TaskData[],
  visibleCount: number,
): VisibleTasksSlice {
  return {
    flatTasks: sortedUnpinnedTasks.slice(0, visibleCount),
    hasMore: sortedUnpinnedTasks.length > visibleCount,
  };
}

export interface LimitedGroupsSlice {
  groups: TaskGroup[];
  hasMore: boolean;
}

/**
 * Caps how many tasks each project group renders in "by-project" mode. A
 * per-group window (rather than a single global cap) keeps every project
 * showing its most-recent tasks, so a busy project can't starve quieter ones
 * out of view entirely. Like {@link sliceVisibleTasks}, this exists to bound
 * the number of mounted task rows — and therefore the per-row workspace and
 * PR-status queries — when a project has accumulated thousands of tasks.
 */
export function limitTasksPerGroup(
  groups: TaskGroup[],
  limitPerGroup: number,
): LimitedGroupsSlice {
  let hasMore = false;
  const limited = groups.map((group) => {
    if (group.tasks.length <= limitPerGroup) return group;
    hasMore = true;
    return { ...group, tasks: group.tasks.slice(0, limitPerGroup) };
  });
  return { groups: limited, hasMore };
}

import type { Task } from "@posthog/shared";
import {
  focusPane,
  type LayoutState,
  newChat,
  openTask,
  panes,
  showToday,
} from "./layout";
import { LEGACY_PREFIX } from "./localChats";

// "waiting" is a chat whose turn ended while the reader was elsewhere.
export type Indicator = "working" | "waiting" | "alive" | "failed" | "asleep";

export interface WorkPage {
  tasks: Task[] | null;
  hasMore: boolean;
  loadingMore: boolean;
  error: string | null;
}

export type SidebarRow =
  | { kind: "heading"; label: "Work" }
  // The day's briefing, shown in the main view while it has no chat; the pane it is in, if any.
  | { kind: "today"; paneId: string | null }
  // Names the list of every task, under the split workspaces.
  | { kind: "section"; label: "All tasks" }
  // A blank row after each workspace.
  | { kind: "gap" }
  | {
      kind: "workspace";
      workspaceId: string;
      label: string;
      expanded: boolean;
      size: number;
    }
  | {
      kind: "task";
      taskId: string | null;
      paneId: string | null;
      title: string;
      indicator: Indicator | null;
      // Runs on this machine rather than in the cloud.
      local: boolean;
      nested: boolean;
      // The final task in its workspace group, drawn with a closing connector.
      last?: boolean;
    }
  | { kind: "loading" }
  | { kind: "signedOut" }
  | { kind: "empty" }
  | { kind: "viewMore" }
  | { kind: "error"; message: string };

export function indicatorFor(
  task: Task | undefined,
  working: boolean,
  waiting = false,
): Indicator {
  if (working) return "working";
  const run = task?.latest_run;
  if (run?.status === "failed") return "failed";
  if (waiting) return "waiting";
  const sandboxStopped =
    (run?.state as Record<string, unknown> | undefined)?.sandbox_alive ===
    false;
  if (
    (run?.status === "queued" || run?.status === "in_progress") &&
    !sandboxStopped
  ) {
    return "alive";
  }
  return "asleep";
}

// A local chat's state is this app's own; a cloud chat has none until the list or a fetch says what its run is doing.
export function chatIndicator(
  taskId: string,
  task: Task | undefined,
  runsHere: boolean,
  {
    working,
    waiting,
    running,
  }: { working: Set<string>; waiting: Set<string>; running: Set<string> },
): Indicator | null {
  if (!runsHere) {
    return task
      ? indicatorFor(task, working.has(taskId), waiting.has(taskId))
      : null;
  }
  if (working.has(taskId)) return "working";
  if (waiting.has(taskId)) return "waiting";
  return running.has(taskId) ? "alive" : "asleep";
}

export interface LocalChatState {
  // Each local chat's task id, with when its session file last changed.
  active: Map<string, number>;
  // Local chats with an agent running in this app.
  running: Set<string>;
}

const NO_LOCAL_CHATS: LocalChatState = {
  active: new Map(),
  running: new Set(),
};

// When something last happened in a chat: the server's clock, or this machine's for a local chat the server hears nothing from.
export const activityOf = (task: Task, local: LocalChatState): number =>
  Math.max(
    Date.parse(task.last_activity_at ?? "") || 0,
    local.active.get(task.id) ?? 0,
  );

// The Work list: the recent page, plus local chats the page does not hold, newest first.
// While more pages exist, a local chat shows only if it is newer than the page's oldest task, so the list reads as one.
function workTasks(
  work: WorkPage,
  byId: Map<string, Task>,
  local: LocalChatState,
): Task[] {
  const listed = work.tasks ?? [];
  const ids = new Set(listed.map((task) => task.id));
  const extra = [...local.active.keys()].flatMap((id) => {
    const task = byId.get(id);
    return task && !ids.has(id) ? [task] : [];
  });
  if (local.active.size === 0) return listed;
  const floor =
    work.hasMore && listed.length > 0
      ? Math.min(...listed.map((task) => activityOf(task, NO_LOCAL_CHATS)))
      : Number.NEGATIVE_INFINITY;
  return [
    ...listed,
    ...extra.filter((task) => activityOf(task, local) >= floor),
  ].sort((a, b) => activityOf(b, local) - activityOf(a, local));
}

export function sidebarRows({
  layout,
  work,
  collapsed,
  working,
  waiting = new Set(),
  known = new Map(),
  titles = new Map(),
  signedIn = true,
  local = NO_LOCAL_CHATS,
}: {
  layout: LayoutState;
  work: WorkPage;
  collapsed: Set<string>;
  working: Set<string>;
  waiting?: Set<string>;
  /** Open tasks outside the recent page, fetched on their own. */
  known?: Map<string, Task>;
  /** Names given with /rename that the work list has not caught up with yet. */
  titles?: Map<string, string>;
  signedIn?: boolean;
  local?: LocalChatState;
}): SidebarRow[] {
  const byId = new Map([
    ...known,
    ...(work.tasks ?? []).map((task): [string, Task] => [task.id, task]),
  ]);
  const tasks = work.tasks === null ? [] : workTasks(work, byId, local);
  const listed = new Set(tasks.map((task) => task.id));
  const isLocal = (taskId: string): boolean =>
    local.active.has(taskId) || taskId.startsWith(LEGACY_PREFIX);
  const taskRow = (
    taskId: string | null,
    paneId: string | null,
    nested: boolean,
    savedTitle?: string,
    last?: boolean,
  ): SidebarRow => {
    const task = taskId ? byId.get(taskId) : undefined;
    const runsHere = taskId !== null && isLocal(taskId);
    return {
      kind: "task",
      taskId,
      paneId,
      title:
        taskId === null
          ? "New chat"
          : titles.get(taskId) || task?.title || savedTitle || "Untitled",
      indicator:
        taskId === null
          ? null
          : chatIndicator(taskId, task, runsHere, {
              working,
              waiting,
              running: local.running,
            }),
      local: runsHere,
      nested,
      last,
    };
  };

  // Today and New chat come first: each names the main view when it shows that, and opens it there otherwise.
  // Split workspaces follow, each followed by a gap. All tasks comes last: single tasks the page does not hold,
  // then the whole list. A split task shows in both places; its row under All tasks jumps to its pane.
  const today: SidebarRow & { kind: "today" } = { kind: "today", paneId: null };
  const newChatRow = taskRow(null, null, false) as SidebarRow & {
    kind: "task";
  };
  const rows: SidebarRow[] = [
    { kind: "heading", label: "Work" },
    today,
    newChatRow,
    { kind: "gap" },
  ];
  const singlePaneOf = new Map<string, string>();
  const unlisted: SidebarRow[] = [];
  layout.workspaces.forEach((workspace, index) => {
    const workspacePanes = panes(workspace.root);
    if (workspacePanes.length === 1) {
      const [pane] = workspacePanes;
      if (pane.taskId === null) {
        if (pane.today) today.paneId = pane.id;
        else newChatRow.paneId = pane.id;
      } else if (listed.has(pane.taskId))
        singlePaneOf.set(pane.taskId, pane.id);
      // Shown once the list has loaded, so loading never lists tasks by saved name alone.
      else if (work.tasks !== null) {
        unlisted.push(taskRow(pane.taskId, pane.id, false, pane.title));
      }
      return;
    }
    const expanded = !collapsed.has(workspace.id);
    rows.push({
      kind: "workspace",
      workspaceId: workspace.id,
      label: workspace.name ?? `Workspace ${index + 1}`,
      expanded,
      size: workspacePanes.length,
    });
    workspacePanes.forEach((pane, paneIndex) => {
      if (!expanded) return;
      const last = paneIndex === workspacePanes.length - 1;
      rows.push(taskRow(pane.taskId, pane.id, true, pane.title, last));
    });
    rows.push({ kind: "gap" });
  });
  rows.push({ kind: "section", label: "All tasks" }, ...unlisted);

  if (!signedIn) {
    rows.push({ kind: "signedOut" });
    return rows;
  }
  if (work.error) rows.push({ kind: "error", message: work.error });
  else if (work.tasks === null) rows.push({ kind: "loading" });
  else if (tasks.length === 0) rows.push({ kind: "empty" });
  for (const task of tasks) {
    rows.push(taskRow(task.id, singlePaneOf.get(task.id) ?? null, false));
  }
  if (work.loadingMore) rows.push({ kind: "loading" });
  else if (work.hasMore) rows.push({ kind: "viewMore" });
  return rows;
}

// Workspace rows only label their group; the keyboard moves between chats.
export const isSelectable = (row: SidebarRow): boolean =>
  row.kind === "task" || row.kind === "today" || row.kind === "viewMore";

export function moveSelection(
  rows: SidebarRow[],
  from: number,
  step: 1 | -1,
): number {
  for (
    let index = from + step;
    index >= 0 && index < rows.length;
    index += step
  ) {
    if (isSelectable(rows[index])) return index;
  }
  return from;
}

export function firstSelectable(rows: SidebarRow[]): number {
  return moveSelection(rows, -1, 1);
}

export function activateRow(
  layout: LayoutState,
  row: SidebarRow,
): LayoutState | "viewMore" {
  switch (row.kind) {
    case "today":
      return row.paneId ? focusPane(layout, row.paneId) : showToday(layout);
    case "task":
      if (row.paneId) return focusPane(layout, row.paneId);
      return row.taskId
        ? openTask(layout, row.taskId, row.title)
        : newChat(layout);
    case "workspace": {
      const workspace = layout.workspaces.find((w) => w.id === row.workspaceId);
      return workspace ? focusPane(layout, workspace.focusedPaneId) : layout;
    }
    case "viewMore":
      return "viewMore";
    default:
      return layout;
  }
}

// Identifies a row across re-renders, so the cursor follows the task rather than its position.
export function selectionKey(row: SidebarRow | undefined): string | null {
  switch (row?.kind) {
    // A split task also has a row under All tasks, so its workspace row goes by its pane.
    case "task":
      return row.taskId && !row.nested
        ? `task:${row.taskId}`
        : `pane:${row.paneId}`;
    case "workspace":
      return `workspace:${row.workspaceId}`;
    case "today":
      return "today";
    case "viewMore":
      return "viewMore";
    default:
      return null;
  }
}

export function cursorIndex(rows: SidebarRow[], key: string | null): number {
  const found =
    key === null ? -1 : rows.findIndex((row) => selectionKey(row) === key);
  return found >= 0 ? found : firstSelectable(rows);
}

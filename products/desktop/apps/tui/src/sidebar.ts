import type { Task } from "@posthog/shared";
import { focusPane, type LayoutState, openTask, panes } from "./layout";

export type Indicator = "working" | "alive" | "failed" | "asleep";

export interface WorkPage {
  tasks: Task[] | null;
  hasMore: boolean;
  loadingMore: boolean;
  error: string | null;
}

export type SidebarRow =
  | { kind: "heading"; label: "Work" }
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
): Indicator {
  if (working) return "working";
  const run = task?.latest_run;
  if (run?.status === "failed") return "failed";
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

export function sidebarRows({
  layout,
  work,
  collapsed,
  working,
  known = new Map(),
  signedIn = true,
}: {
  layout: LayoutState;
  work: WorkPage;
  collapsed: Set<string>;
  working: Set<string>;
  /** Open tasks outside the recent page, fetched on their own. */
  known?: Map<string, Task>;
  signedIn?: boolean;
}): SidebarRow[] {
  const listed = new Set((work.tasks ?? []).map((task) => task.id));
  const byId = new Map([
    ...known,
    ...(work.tasks ?? []).map((task): [string, Task] => [task.id, task]),
  ]);
  const taskRow = (
    taskId: string | null,
    paneId: string | null,
    nested: boolean,
    savedTitle?: string,
    last?: boolean,
  ): SidebarRow => {
    const task = taskId ? byId.get(taskId) : undefined;
    return {
      kind: "task",
      taskId,
      paneId,
      title:
        taskId === null ? "New chat" : task?.title || savedTitle || "Untitled",
      // No status until the list or a fetch says what state the run is in.
      indicator:
        taskId === null || !task
          ? null
          : indicatorFor(task, working.has(taskId)),
      nested,
      last,
    };
  };

  // Open chats come first: new chats, then split workspaces, then single tasks the page does not hold.
  const rows: SidebarRow[] = [{ kind: "heading", label: "Work" }];
  const singlePaneOf = new Map<string, string>();
  const splitTasks = new Set<string>();
  const unlisted: SidebarRow[] = [];
  layout.workspaces.forEach((workspace, index) => {
    const workspacePanes = panes(workspace.root);
    if (workspacePanes.length === 1) {
      const [pane] = workspacePanes;
      if (pane.taskId === null) rows.push(taskRow(null, pane.id, false));
      else if (listed.has(pane.taskId)) singlePaneOf.set(pane.taskId, pane.id);
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
      label: `Workspace ${index + 1}`,
      expanded,
      size: workspacePanes.length,
    });
    workspacePanes.forEach((pane, paneIndex) => {
      if (pane.taskId) splitTasks.add(pane.taskId);
      if (!expanded) return;
      const last = paneIndex === workspacePanes.length - 1;
      rows.push(taskRow(pane.taskId, pane.id, true, pane.title, last));
    });
  });
  rows.push(...unlisted);

  if (!signedIn) {
    rows.push({ kind: "signedOut" });
    return rows;
  }
  if (work.error) rows.push({ kind: "error", message: work.error });
  else if (work.tasks === null) rows.push({ kind: "loading" });
  else if (work.tasks.length === 0) rows.push({ kind: "empty" });
  for (const task of work.tasks ?? []) {
    if (splitTasks.has(task.id)) continue;
    rows.push(taskRow(task.id, singlePaneOf.get(task.id) ?? null, false));
  }
  if (work.loadingMore) rows.push({ kind: "loading" });
  else if (work.hasMore) rows.push({ kind: "viewMore" });
  return rows;
}

// Workspace rows only label their group; the keyboard moves between chats.
const isSelectable = (row: SidebarRow): boolean =>
  row.kind === "task" || row.kind === "viewMore";

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
    case "task":
      if (row.paneId) return focusPane(layout, row.paneId);
      return row.taskId ? openTask(layout, row.taskId, row.title) : layout;
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
    case "task":
      return row.taskId ? `task:${row.taskId}` : `pane:${row.paneId}`;
    case "workspace":
      return `workspace:${row.workspaceId}`;
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

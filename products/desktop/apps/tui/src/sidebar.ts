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
  | { kind: "heading"; label: "Tasks" | "Work" }
  | { kind: "workspace"; workspaceId: string; label: string; expanded: boolean }
  | {
      kind: "task";
      taskId: string | null;
      paneId: string | null;
      title: string;
      indicator: Indicator | null;
      nested: boolean;
    }
  | { kind: "loading" }
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
}: {
  layout: LayoutState;
  work: WorkPage;
  collapsed: Set<string>;
  working: Set<string>;
}): SidebarRow[] {
  const byId = new Map((work.tasks ?? []).map((task) => [task.id, task]));
  const taskRow = (
    taskId: string | null,
    paneId: string | null,
    nested: boolean,
  ): SidebarRow => {
    const task = taskId ? byId.get(taskId) : undefined;
    return {
      kind: "task",
      taskId,
      paneId,
      title: taskId === null ? "New chat" : (task?.title ?? "Loading…"),
      indicator:
        taskId === null ? null : indicatorFor(task, working.has(taskId)),
      nested,
    };
  };

  const rows: SidebarRow[] = [{ kind: "heading", label: "Tasks" }];
  layout.workspaces.forEach((workspace, index) => {
    const workspacePanes = panes(workspace.root);
    if (workspacePanes.length === 1) {
      rows.push(taskRow(workspacePanes[0].taskId, workspacePanes[0].id, false));
      return;
    }
    const expanded = !collapsed.has(workspace.id);
    rows.push({
      kind: "workspace",
      workspaceId: workspace.id,
      label: `Workspace ${index + 1}`,
      expanded,
    });
    if (expanded) {
      for (const pane of workspacePanes) {
        rows.push(taskRow(pane.taskId, pane.id, true));
      }
    }
  });

  rows.push({ kind: "heading", label: "Work" });
  if (work.error) rows.push({ kind: "error", message: work.error });
  else if (work.tasks === null) rows.push({ kind: "loading" });
  else if (work.tasks.length === 0) rows.push({ kind: "empty" });
  for (const task of work.tasks ?? []) rows.push(taskRow(task.id, null, false));
  if (work.loadingMore) rows.push({ kind: "loading" });
  else if (work.hasMore) rows.push({ kind: "viewMore" });
  return rows;
}

const isSelectable = (row: SidebarRow): boolean =>
  row.kind === "task" || row.kind === "workspace" || row.kind === "viewMore";

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
      return row.taskId ? openTask(layout, row.taskId) : layout;
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

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export type PaneNode = { kind: "pane"; id: string; taskId: string | null };
export type LayoutNode =
  | PaneNode
  | { kind: "split"; direction: "row" | "column"; children: LayoutNode[] };

export interface Workspace {
  id: string;
  root: LayoutNode;
  focusedPaneId: string;
}

export interface LayoutState {
  workspaces: Workspace[];
  activeWorkspaceId: string;
  focus: "sidebar" | "pane";
}

const LAYOUT_PATH = join(homedir(), ".config", "posthog-tui", "layout.json");

const newId = (): string => globalThis.crypto.randomUUID();

function newWorkspace(taskId: string | null): Workspace {
  const pane: PaneNode = { kind: "pane", id: newId(), taskId };
  return { id: newId(), root: pane, focusedPaneId: pane.id };
}

export function initialLayout(): LayoutState {
  const workspace = newWorkspace(null);
  return {
    workspaces: [workspace],
    activeWorkspaceId: workspace.id,
    focus: "pane",
  };
}

export function paneIds(node: LayoutNode): string[] {
  return node.kind === "pane" ? [node.id] : node.children.flatMap(paneIds);
}

export function panes(node: LayoutNode): PaneNode[] {
  return node.kind === "pane" ? [node] : node.children.flatMap(panes);
}

export function activeWorkspace(state: LayoutState): Workspace {
  return (
    state.workspaces.find((w) => w.id === state.activeWorkspaceId) ??
    state.workspaces[0]
  );
}

function mapPanes(
  node: LayoutNode,
  fn: (pane: PaneNode) => LayoutNode,
): LayoutNode {
  return node.kind === "pane"
    ? fn(node)
    : { ...node, children: node.children.map((child) => mapPanes(child, fn)) };
}

function updateActive(
  state: LayoutState,
  fn: (workspace: Workspace) => Workspace,
): LayoutState {
  const active = activeWorkspace(state);
  return {
    ...state,
    workspaces: state.workspaces.map((w) => (w.id === active.id ? fn(w) : w)),
  };
}

export function splitFocused(
  state: LayoutState,
  direction: "row" | "column",
): LayoutState {
  const pane: PaneNode = { kind: "pane", id: newId(), taskId: null };
  return {
    ...updateActive(state, (workspace) => ({
      ...workspace,
      root: mapPanes(workspace.root, (target) =>
        target.id === workspace.focusedPaneId
          ? { kind: "split", direction, children: [target, pane] }
          : target,
      ),
      focusedPaneId: pane.id,
    })),
    focus: "pane",
  };
}

export function focusPane(state: LayoutState, paneId: string): LayoutState {
  const workspace = state.workspaces.find((w) =>
    paneIds(w.root).includes(paneId),
  );
  if (!workspace) return state;
  return {
    workspaces: state.workspaces.map((w) =>
      w.id === workspace.id ? { ...w, focusedPaneId: paneId } : w,
    ),
    activeWorkspaceId: workspace.id,
    focus: "pane",
  };
}

export function focusSidebar(state: LayoutState): LayoutState {
  return { ...state, focus: "sidebar" };
}

// Focus order is the sidebar, then each pane of the active workspace in layout order.
export function cycleFocus(state: LayoutState, step: 1 | -1): LayoutState {
  const ids = paneIds(activeWorkspace(state).root);
  const order = ["sidebar", ...ids];
  const current =
    state.focus === "sidebar"
      ? 0
      : order.indexOf(activeWorkspace(state).focusedPaneId);
  const next = order[(current + step + order.length) % order.length];
  return next === "sidebar" ? focusSidebar(state) : focusPane(state, next);
}

export function openTask(state: LayoutState, taskId: string): LayoutState {
  const open = state.workspaces
    .flatMap((w) => panes(w.root))
    .find((pane) => pane.taskId === taskId);
  if (open) return focusPane(state, open.id);

  const active = activeWorkspace(state);
  const focused = panes(active.root).find((p) => p.id === active.focusedPaneId);
  if (focused && focused.taskId === null) {
    return {
      ...updateActive(state, (workspace) => ({
        ...workspace,
        root: mapPanes(workspace.root, (pane) =>
          pane.id === focused.id ? { ...pane, taskId } : pane,
        ),
      })),
      focus: "pane",
    };
  }

  const workspace = newWorkspace(taskId);
  return {
    workspaces: [...state.workspaces, workspace],
    activeWorkspaceId: workspace.id,
    focus: "pane",
  };
}

export function closeFocused(state: LayoutState): LayoutState | "quit" {
  const active = activeWorkspace(state);
  const ids = paneIds(active.root);

  if (ids.length === 1) {
    const index = state.workspaces.indexOf(active);
    const workspaces = state.workspaces.filter((w) => w.id !== active.id);
    if (workspaces.length === 0) return "quit";
    return {
      workspaces,
      activeWorkspaceId: workspaces[Math.max(0, index - 1)].id,
      focus: "pane",
    };
  }

  const remove = (node: LayoutNode): LayoutNode | null => {
    if (node.kind === "pane") {
      return node.id === active.focusedPaneId ? null : node;
    }
    const children = node.children
      .map(remove)
      .filter((child): child is LayoutNode => child !== null);
    return children.length === 1 ? children[0] : { ...node, children };
  };
  const root = remove(active.root) as LayoutNode;
  const index = ids.indexOf(active.focusedPaneId);
  const focusedPaneId = paneIds(root)[Math.max(0, index - 1)];
  return {
    ...updateActive(state, (workspace) => ({
      ...workspace,
      root,
      focusedPaneId,
    })),
    focus: "pane",
  };
}

export function loadLayout(path: string = LAYOUT_PATH): LayoutState {
  try {
    const state = JSON.parse(readFileSync(path, "utf8")) as LayoutState;
    const valid =
      state.workspaces.length > 0 &&
      state.workspaces.every((w) => paneIds(w.root).includes(w.focusedPaneId));
    return valid ? state : initialLayout();
  } catch {
    return initialLayout();
  }
}

export function saveLayout(
  state: LayoutState,
  path: string = LAYOUT_PATH,
): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(state));
}

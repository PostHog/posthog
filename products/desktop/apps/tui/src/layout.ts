import {
  existsSync,
  mkdirSync,
  readFileSync,
  renameSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export type PaneNode = {
  kind: "pane";
  id: string;
  taskId: string | null;
  // Saved so the pane and sidebar can name the task before the work list loads.
  title?: string;
};
export type LayoutNode =
  | PaneNode
  | { kind: "split"; direction: "row" | "column"; children: LayoutNode[] };

export interface Workspace {
  id: string;
  root: LayoutNode;
  focusedPaneId: string;
  // Set with /rename-workspace; the sidebar numbers a workspace without one.
  name?: string;
}

export interface LayoutState {
  workspaces: Workspace[];
  activeWorkspaceId: string;
  focus: "sidebar" | "pane";
}

const LAYOUT_PATH = join(homedir(), ".config", "posthog-tui", "layout.json");

// Each account has its own file, so a sign-out and a later sign-in bring its workspaces back. Signed out, or signed in before the session recorded an account, the layout uses the shared file.
export const layoutPath = (account?: string): string =>
  account ? join(dirname(LAYOUT_PATH), `layout.${account}.json`) : LAYOUT_PATH;

const newId = (): string => globalThis.crypto.randomUUID();

function newWorkspace(taskId: string | null, title?: string): Workspace {
  const pane: PaneNode = { kind: "pane", id: newId(), taskId, title };
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

export function allPanes(state: LayoutState): PaneNode[] {
  return state.workspaces.flatMap((w) => panes(w.root));
}

export function findPane(
  state: LayoutState,
  paneId: string,
): PaneNode | undefined {
  return allPanes(state).find((pane) => pane.id === paneId);
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

export function openTask(
  state: LayoutState,
  taskId: string,
  title?: string,
): LayoutState {
  const open = allPanes(state).find((pane) => pane.taskId === taskId);
  if (open) return focusPane(state, open.id);

  const active = activeWorkspace(state);
  const focused = panes(active.root).find((p) => p.id === active.focusedPaneId);
  if (focused && focused.taskId === null) {
    return {
      ...updateActive(state, (workspace) => ({
        ...workspace,
        root: mapPanes(workspace.root, (pane) =>
          pane.id === focused.id ? { ...pane, taskId, title } : pane,
        ),
      })),
      focus: "pane",
    };
  }

  // Outside splits there is one main view; a task opened there replaces what it showed.
  const main =
    active.root.kind === "pane"
      ? active
      : state.workspaces.find((w) => w.root.kind === "pane");
  if (main) {
    const pane = main.root as PaneNode;
    return {
      workspaces: state.workspaces.map((w) =>
        w.id === main.id ? { ...w, root: { ...pane, taskId, title } } : w,
      ),
      activeWorkspaceId: main.id,
      focus: "pane",
    };
  }
  const workspace = newWorkspace(taskId, title);
  return {
    workspaces: [...state.workspaces, workspace],
    activeWorkspaceId: workspace.id,
    focus: "pane",
  };
}

// Empties the main view (making one if only splits exist) and focuses it.
export function newChat(state: LayoutState): LayoutState {
  const main = state.workspaces.find((w) => w.root.kind === "pane");
  if (!main) {
    const workspace = newWorkspace(null);
    return {
      workspaces: [...state.workspaces, workspace],
      activeWorkspaceId: workspace.id,
      focus: "pane",
    };
  }
  const pane = main.root as PaneNode;
  return {
    workspaces: state.workspaces.map((w) =>
      w.id === main.id
        ? { ...w, root: { ...pane, taskId: null, title: undefined } }
        : w,
    ),
    activeWorkspaceId: main.id,
    focus: "pane",
  };
}

// A new chat from a pane in a split takes that pane's place; from anywhere else it clears the main view.
export function newChatIn(state: LayoutState, paneId: string): LayoutState {
  const workspace = workspaceOf(state, paneId);
  if (!workspace || workspace.root.kind === "pane") return newChat(state);
  return {
    workspaces: state.workspaces.map((w) =>
      w.id === workspace.id
        ? {
            ...w,
            root: mapPanes(w.root, (pane) =>
              pane.id === paneId
                ? { ...pane, taskId: null, title: undefined }
                : pane,
            ),
            focusedPaneId: paneId,
          }
        : w,
    ),
    activeWorkspaceId: workspace.id,
    focus: "pane",
  };
}

// The panes in reading order, laid out in rows as the desktop app's Optimize does: as many columns as the square root
// of the count, rounded up, and as many rows as that takes. Panes are shared across the rows as evenly as they go,
// the top rows taking any extra, so no cell is left empty.
function grid(panes: PaneNode[]): LayoutNode {
  if (panes.length === 1) return panes[0];
  const columns = Math.ceil(Math.sqrt(panes.length));
  const rows = Math.ceil(panes.length / columns);
  const base = Math.floor(panes.length / rows);
  const extra = panes.length % rows;
  const lines: LayoutNode[] = [];
  let next = 0;
  for (let row = 0; row < rows; row++) {
    const size = base + (row < extra ? 1 : 0);
    const cells = panes.slice(next, next + size);
    next += size;
    lines.push(
      cells.length === 1
        ? cells[0]
        : { kind: "split", direction: "row", children: cells },
    );
  }
  return lines.length === 1
    ? lines[0]
    : { kind: "split", direction: "column", children: lines };
}

// Evens out a workspace's panes; null when they are already as even as they can be.
export function optimizeWorkspace(
  state: LayoutState,
  workspaceId: string,
): LayoutState | null {
  const workspace = state.workspaces.find((w) => w.id === workspaceId);
  if (!workspace) return null;
  const root = grid(panes(workspace.root));
  if (JSON.stringify(root) === JSON.stringify(workspace.root)) return null;
  return {
    ...state,
    workspaces: state.workspaces.map((w) =>
      w.id === workspaceId ? { ...w, root } : w,
    ),
  };
}

// Shows a split pane's task full width in the main view, the way All tasks opens it, and leaves the split as it is.
export function expandPane(state: LayoutState, paneId: string): LayoutState {
  const pane = findPane(state, paneId);
  if (!pane?.taskId) return state;
  const main = state.workspaces.find((w) => w.root.kind === "pane");
  if (!main) {
    const workspace = newWorkspace(pane.taskId, pane.title);
    return {
      workspaces: [...state.workspaces, workspace],
      activeWorkspaceId: workspace.id,
      focus: "pane",
    };
  }
  const root = main.root as PaneNode;
  return {
    workspaces: state.workspaces.map((w) =>
      w.id === main.id
        ? { ...w, root: { ...root, taskId: pane.taskId, title: pane.title } }
        : w,
    ),
    activeWorkspaceId: main.id,
    focus: "pane",
  };
}

// Splits are kept; of the single-pane views, only the active one (or else the last) survives.
function withOneMainView(state: LayoutState): LayoutState {
  const singles = state.workspaces.filter((w) => w.root.kind === "pane");
  const keep =
    singles.find((w) => w.id === state.activeWorkspaceId) ?? singles.at(-1);
  const workspaces = state.workspaces.filter(
    (w) => w.root.kind !== "pane" || w === keep,
  );
  return {
    ...state,
    workspaces,
    activeWorkspaceId: workspaces.some((w) => w.id === state.activeWorkspaceId)
      ? state.activeWorkspaceId
      : workspaces[0].id,
  };
}

export function assignTask(
  state: LayoutState,
  paneId: string,
  taskId: string,
  title?: string,
): LayoutState {
  return {
    ...state,
    workspaces: state.workspaces.map((workspace) => ({
      ...workspace,
      root: mapPanes(workspace.root, (pane) =>
        pane.id === paneId ? { ...pane, taskId, title } : pane,
      ),
    })),
  };
}

// Moves every pane showing one task id over to another, such as a local chat that just got its task row.
export function renameTask(
  state: LayoutState,
  from: string,
  to: string,
  title?: string,
): LayoutState {
  return {
    ...state,
    workspaces: state.workspaces.map((workspace) => ({
      ...workspace,
      root: mapPanes(workspace.root, (pane) =>
        pane.taskId === from
          ? { ...pane, taskId: to, title: title ?? pane.title }
          : pane,
      ),
    })),
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

// The workspace a pane sits in, if any.
export function workspaceOf(
  state: LayoutState,
  paneId: string,
): Workspace | undefined {
  return state.workspaces.find((workspace) =>
    paneIds(workspace.root).includes(paneId),
  );
}

export function renameWorkspace(
  state: LayoutState,
  workspaceId: string,
  name: string,
): LayoutState {
  return {
    ...state,
    workspaces: state.workspaces.map((workspace) =>
      workspace.id === workspaceId ? { ...workspace, name } : workspace,
    ),
  };
}

// The shared file held every layout before accounts had their own. An account without its own file takes it over,
// so an upgrade keeps its workspaces and a later sign-out starts from a fresh layout instead of showing them.
export function adoptSharedLayout(
  path: string,
  shared: string = LAYOUT_PATH,
): void {
  if (path === shared || existsSync(path) || !existsSync(shared)) return;
  renameSync(shared, path);
}

export function loadLayout(path: string = LAYOUT_PATH): LayoutState {
  try {
    const state = JSON.parse(readFileSync(path, "utf8")) as LayoutState;
    const valid =
      state.workspaces.length > 0 &&
      state.workspaces.every((w) => paneIds(w.root).includes(w.focusedPaneId));
    return valid ? withOneMainView(state) : initialLayout();
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

// Cell sizes along a split: whole rows or columns, with each cell after the first carrying its one-cell divider.
export function splitSizes(total: number, count: number): number[] {
  const content = Math.max(0, total - (count - 1));
  const base = Math.floor(content / count);
  const extra = content % count;
  return Array.from(
    { length: count },
    (_, index) => base + (index < extra ? 1 : 0) + (index > 0 ? 1 : 0),
  );
}

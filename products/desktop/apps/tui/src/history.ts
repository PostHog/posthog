import {
  activeWorkspace,
  assignTask,
  findPane,
  focusPane,
  type LayoutState,
  newChatIn,
} from "./layout";

// Where the reader was: a pane, and the chat it showed.
export interface Spot {
  paneId: string;
  taskId: string | null;
}

export interface History {
  // Spots before the current one, oldest first.
  back: Spot[];
  // Spots left by going back, nearest first.
  forward: Spot[];
  current: Spot | null;
}

export const noHistory: History = { back: [], forward: [], current: null };

const LIMIT = 50;

export function spotOf(layout: LayoutState): Spot {
  const workspace = activeWorkspace(layout);
  return {
    paneId: workspace.focusedPaneId,
    taskId: findPane(layout, workspace.focusedPaneId)?.taskId ?? null,
  };
}

const same = (a: Spot | null, b: Spot): boolean =>
  a !== null && a.paneId === b.paneId && a.taskId === b.taskId;

// Notes the spot the layout is on; a spot already current is not noted again, and a new one drops what was ahead.
export function visited(history: History, spot: Spot): History {
  if (same(history.current, spot)) return history;
  return {
    back: history.current
      ? [...history.back, history.current].slice(-LIMIT)
      : history.back,
    forward: [],
    current: spot,
  };
}

// Focuses the spot's pane, with the chat it showed; a pane since closed cannot be gone to.
function goTo(layout: LayoutState, spot: Spot): LayoutState | null {
  const pane = findPane(layout, spot.paneId);
  if (!pane) return null;
  const focused = focusPane(layout, spot.paneId);
  if (pane.taskId === spot.taskId) return focused;
  return spot.taskId
    ? assignTask(focused, spot.paneId, spot.taskId)
    : newChatIn(focused, spot.paneId);
}

function step(
  history: History,
  layout: LayoutState,
  direction: "back" | "forward",
): { history: History; layout: LayoutState } | null {
  const from = direction === "back" ? [...history.back] : [...history.forward];
  const to = direction === "back" ? [...history.forward] : [...history.back];
  while (from.length > 0) {
    const spot = direction === "back" ? from.pop() : from.shift();
    if (!spot) break;
    const next = goTo(layout, spot);
    if (!next) continue;
    if (history.current) {
      if (direction === "back") to.unshift(history.current);
      else to.push(history.current);
    }
    return {
      layout: next,
      history:
        direction === "back"
          ? { back: from, forward: to, current: spot }
          : { back: to, forward: from, current: spot },
    };
  }
  return null;
}

export function back(
  history: History,
  layout: LayoutState,
): { history: History; layout: LayoutState } | null {
  return step(history, layout, "back");
}

export function forward(
  history: History,
  layout: LayoutState,
): { history: History; layout: LayoutState } | null {
  return step(history, layout, "forward");
}

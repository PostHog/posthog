export interface TurnState {
  // The chat mid-turn in each pane, by pane id.
  working: Map<string, string>;
  // Chats whose turn ended while the reader was on another pane, until they visit.
  waiting: Set<string>;
}

export const noTurns: TurnState = { working: new Map(), waiting: new Set() };

// A pane says on every render which chat it shows and whether that chat is mid-turn; an unchanged report returns the same state.
export function reportTurn(
  state: TurnState,
  paneId: string,
  taskId: string | null,
  working: boolean,
  focused: boolean,
): TurnState {
  const was = state.working.get(paneId);
  const now = working && taskId ? taskId : undefined;
  if (was === now) return state;
  const next = {
    working: new Map(state.working),
    waiting: new Set(state.waiting),
  };
  if (now) {
    next.working.set(paneId, now);
    next.waiting.delete(now);
  } else next.working.delete(paneId);
  if (was && !now && was === taskId && !focused) next.waiting.add(was);
  return next;
}

export function visit(state: TurnState, taskId: string | null): TurnState {
  if (!taskId || !state.waiting.has(taskId)) return state;
  const waiting = new Set(state.waiting);
  waiting.delete(taskId);
  return { ...state, waiting };
}

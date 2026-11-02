import type { AgentRuntime } from "@posthog/shared";
import type { RunView } from "./runs";
import { transcriptFrom } from "./transcript";

export interface TurnState {
  // Chats mid-turn.
  working: Set<string>;
  // Chats whose turn ended while the reader was on another chat, until they visit.
  waiting: Set<string>;
}

export const noTurns: TurnState = { working: new Set(), waiting: new Set() };

// A chat's turn opened or closed; an unchanged report returns the same state.
export function settle(
  state: TurnState,
  taskId: string,
  working: boolean,
  seen: boolean,
): TurnState {
  if (state.working.has(taskId) === working) return state;
  const next = {
    working: new Set(state.working),
    waiting: new Set(state.waiting),
  };
  if (working) {
    next.working.add(taskId);
    next.waiting.delete(taskId);
  } else {
    next.working.delete(taskId);
    if (!seen) next.waiting.add(taskId);
  }
  return next;
}

export function visit(state: TurnState, taskId: string | null): TurnState {
  if (!taskId || !state.waiting.has(taskId)) return state;
  const waiting = new Set(state.waiting);
  waiting.delete(taskId);
  return { ...state, waiting };
}

// The run is up and has a prompt it has not finished answering.
export function midTurn(
  view: RunView,
  runtime: AgentRuntime | undefined,
): boolean {
  return (
    view.loaded &&
    (view.status === "queued" || view.status === "in_progress") &&
    transcriptFrom(runtime, view.entries).turnOpen
  );
}

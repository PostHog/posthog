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

// What the inbox needs to know about a chat's last turn, from its log.
export interface TurnFacts {
  turnEndedAt: number | null;
  shells: number;
  wake: boolean;
}

// A log's reading, kept per entries array: a log is replaced on every update, never changed in place, so an
// unchanged one is never read twice. The transcript is rebuilt from the whole log, which costs a frame when long.
const readings = new WeakMap<
  object,
  { runtime: AgentRuntime | undefined; turnOpen: boolean; facts: TurnFacts }
>();

// Whether a chat is mid-turn, and its last turn's facts. The facts are null while a turn runs: only a settled turn
// has an end to report, so a streaming chat adds nothing to the inbox's cost.
export function readTurn(
  view: RunView,
  runtime: AgentRuntime | undefined,
): { working: boolean; facts: TurnFacts | null } {
  if (!view.loaded) return { working: false, facts: null };
  let reading = readings.get(view.entries);
  if (!reading || reading.runtime !== runtime) {
    const transcript = transcriptFrom(runtime, view.entries);
    reading = {
      runtime,
      turnOpen: transcript.turnOpen,
      facts: {
        turnEndedAt: transcript.lastTurn?.endedAt ?? null,
        shells: transcript.shells,
        wake: transcript.wake !== null,
      },
    };
    readings.set(view.entries, reading);
  }
  const working =
    (view.status === "queued" || view.status === "in_progress") &&
    reading.turnOpen;
  return { working, facts: working ? null : reading.facts };
}

// The run is up and has a prompt it has not finished answering.
export function midTurn(
  view: RunView,
  runtime: AgentRuntime | undefined,
): boolean {
  return readTurn(view, runtime).working;
}

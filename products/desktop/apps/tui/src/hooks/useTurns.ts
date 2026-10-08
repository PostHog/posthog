import type { AgentRuntime, Task } from "@posthog/shared";
import { useEffect, useRef, useState } from "react";
import { activeWorkspace, findPane, type LayoutState, panes } from "../layout";
import type { LocalAgent } from "../local";
import type { CloudRuns, RunView } from "../runs";
import { midTurn, noTurns, settle, visit } from "../turns";

// How often a watched chat's log is read for its turn, so a fast stream costs one reading a second.
const CHECK_MS = 1_000;

export interface Turns {
  // Chats mid-turn.
  working: Set<string>;
  // Chats whose turn ended while the reader was on another chat.
  waiting: Set<string>;
}

// Which chats are working and which finished unseen, for the sidebar.
// A chat is watched from when it is on screen until its turn ends, so one that leaves the screen mid-turn still reports.
export function useTurns({
  layout,
  runs,
  taskOf,
  localSessions,
}: {
  layout: LayoutState;
  runs: CloudRuns | null;
  taskOf: (taskId: string | null) => Task | undefined;
  localSessions: Map<string, LocalAgent>;
}): Turns {
  const [turns, setTurns] = useState(noTurns);
  const workspace = activeWorkspace(layout);
  const focusedTaskId =
    findPane(layout, workspace.focusedPaneId)?.taskId ?? null;
  const focused = useRef(focusedTaskId);
  focused.current = focusedTaskId;
  useEffect(() => {
    setTurns((state) => visit(state, focusedTaskId));
  }, [focusedTaskId]);

  const subscriptions = useRef(new Map<string, () => void>());
  // Each watched chat's latest view, until the next check reads it.
  const unread = useRef(
    new Map<string, { view: RunView; runtime: AgentRuntime | undefined }>(),
  );
  // Subscriptions stay open across renders: a new one starts from the run's saved snapshot and would miss what came since.
  useEffect(() => {
    const onScreen = panes(workspace.root).flatMap((pane) =>
      pane.taskId ? [pane.taskId] : [],
    );
    const wanted = new Map<string, () => () => void>();
    for (const taskId of new Set([...onScreen, ...turns.working])) {
      const task = taskOf(taskId);
      const local = localSessions.get(taskId);
      const runtime = local?.runtime ?? task?.runtime ?? "pi";
      const onView = (view: RunView): void => {
        unread.current.set(taskId, { view, runtime });
      };
      const run = task?.latest_run;
      if (local) wanted.set(`${taskId}:local`, () => local.watch(onView));
      else if (runs && run && run.environment !== "local")
        wanted.set(
          `${taskId}:${run.id}`,
          () => runs.watch(taskId, run.id, onView).stop,
        );
    }
    for (const [key, stop] of subscriptions.current) {
      if (wanted.has(key)) continue;
      stop();
      subscriptions.current.delete(key);
    }
    for (const [key, start] of wanted) {
      if (!subscriptions.current.has(key))
        subscriptions.current.set(key, start());
    }
  });
  useEffect(() => {
    const open = subscriptions.current;
    const timer = setInterval(() => {
      for (const [taskId, { view, runtime }] of unread.current) {
        const working = midTurn(view, runtime);
        setTurns((state) =>
          settle(state, taskId, working, taskId === focused.current),
        );
      }
      unread.current.clear();
    }, CHECK_MS);
    return () => {
      clearInterval(timer);
      for (const stop of open.values()) stop();
      open.clear();
    };
  }, []);

  return turns;
}

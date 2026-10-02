import { useEffect, useMemo, useState } from "react";
import {
  activeWorkspace,
  findPane,
  type LayoutState,
  paneIds,
} from "../layout";
import { noTurns, reportTurn, visit } from "../turns";

export interface Turns {
  // Chats mid-turn in a pane on screen.
  working: Set<string>;
  // Chats whose turn ended while the reader was on another pane.
  waiting: Set<string>;
  report: (paneId: string, taskId: string | null, working: boolean) => void;
}

// Which open chats are working and which finished unseen, for the sidebar.
export function useTurns(layout: LayoutState): Turns {
  const [turns, setTurns] = useState(noTurns);
  const workspace = activeWorkspace(layout);
  const focusedPaneId = workspace.focusedPaneId;
  const focusedTaskId = findPane(layout, focusedPaneId)?.taskId ?? null;
  useEffect(() => {
    setTurns((state) => visit(state, focusedTaskId));
  }, [focusedTaskId]);
  // A pane off screen reports nothing, so what it last said is not shown.
  const working = useMemo(() => {
    const onScreen = new Set(paneIds(workspace.root));
    return new Set(
      [...turns.working].flatMap(([paneId, taskId]) =>
        onScreen.has(paneId) ? [taskId] : [],
      ),
    );
  }, [turns.working, workspace.root]);
  return {
    working,
    waiting: turns.waiting,
    report: (paneId, taskId, working) =>
      setTurns((state) =>
        reportTurn(state, paneId, taskId, working, paneId === focusedPaneId),
      ),
  };
}

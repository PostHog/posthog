import {
  type CommandCenterSession,
  selectCommandCenterSession,
} from "@posthog/core/command-center/cells";
import { useMemo } from "react";
import { shallow } from "zustand/shallow";
import { useSessionStore } from "../../sessions/sessionStore";

export function useCommandCenterSessions(
  taskIds: (string | null)[],
): Map<string, CommandCenterSession> {
  const sessions = useSessionStore(
    (state) =>
      taskIds.map((taskId) => {
        const runId = taskId ? state.taskIdIndex[taskId] : undefined;
        return selectCommandCenterSession(
          runId ? state.sessions[runId] : undefined,
        );
      }),
    (previous, next) =>
      previous.length === next.length &&
      previous.every((session, index) => shallow(session, next[index])),
  );
  return useMemo(() => {
    const byTaskId = new Map<string, CommandCenterSession>();
    for (let index = 0; index < taskIds.length; index++) {
      const taskId = taskIds[index];
      const session = sessions[index];
      if (taskId && session) byTaskId.set(taskId, session);
    }
    return byTaskId;
  }, [taskIds, sessions]);
}

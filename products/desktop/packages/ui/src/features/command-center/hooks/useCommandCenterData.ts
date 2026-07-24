import {
  buildCommandCenterCells,
  type CommandCenterCellData,
} from "@posthog/core/command-center/cells";
import {
  buildStatusSummary,
  type CellStatus,
  type StatusSummary,
} from "@posthog/core/command-center/status";
import type { Task } from "@posthog/shared/domain-types";
import { useMemo } from "react";
import type { AgentSession } from "../../sessions/sessionStore";
import { useSessions } from "../../sessions/useSession";
import { useTasks } from "../../tasks/useTasks";
import { useWorkspaces } from "../../workspace/useWorkspace";
import { useCommandCenterStore } from "../commandCenterStore";

export type { CellStatus, StatusSummary, CommandCenterCellData };
export { deriveStatus } from "@posthog/core/command-center/status";

export function useCommandCenterData(): {
  cells: CommandCenterCellData[];
  summary: StatusSummary;
} {
  const storeCells = useCommandCenterStore((s) => s.cells);
  const { data: tasks = [] } = useTasks();
  const sessions = useSessions();
  const { data: workspaces } = useWorkspaces();

  const taskById = useMemo(() => {
    const map = new Map<string, Task>();
    for (const task of tasks) {
      map.set(task.id, task);
    }
    return map;
  }, [tasks]);

  const sessionByTaskId = useMemo(() => {
    const map = new Map<string, AgentSession>();
    for (const session of Object.values(sessions)) {
      if (session.taskId) {
        map.set(session.taskId, session);
      }
    }
    return map;
  }, [sessions]);

  const cells = useMemo(
    () =>
      buildCommandCenterCells(storeCells, {
        taskById,
        sessionByTaskId,
        workspaces,
      }),
    [storeCells, taskById, sessionByTaskId, workspaces],
  );

  const summary = useMemo(() => buildStatusSummary(cells), [cells]);

  return { cells, summary };
}

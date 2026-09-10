import {
  type CommandCenterCellData as BaseCommandCenterCellData,
  buildCommandCenterCells,
} from "@posthog/core/command-center/cells";
import {
  buildStatusSummary,
  type CellStatus,
  hasUnseenCompletion,
  type StatusSummary,
} from "@posthog/core/command-center/status";
import { taskActivityAt } from "@posthog/core/tasks/taskActivity";
import type { Task } from "@posthog/shared/domain-types";
import { useMemo } from "react";
import type { AgentSession } from "../../sessions/sessionStore";
import { useSessions } from "../../sessions/useSession";
import { useTaskViewed } from "../../sidebar/useTaskViewed";
import { useTasks } from "../../tasks/useTasks";
import { useWorkspaces } from "../../workspace/useWorkspace";
import { useCommandCenterStore } from "../commandCenterStore";

export type CommandCenterCellData = BaseCommandCenterCellData & {
  hasUnseenCompletion: boolean;
};

export type { CellStatus, StatusSummary };

export function useCommandCenterData(): {
  cells: CommandCenterCellData[];
  summary: StatusSummary;
} {
  const storeCells = useCommandCenterStore((s) => s.cells);
  const { data: tasks = [] } = useTasks();
  const sessions = useSessions();
  const { data: workspaces } = useWorkspaces();
  const { timestamps } = useTaskViewed();

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

  const cells = useMemo(() => {
    const baseCells = buildCommandCenterCells(storeCells, {
      taskById,
      sessionByTaskId,
      workspaces,
    });
    return baseCells.map((cell) => ({
      ...cell,
      hasUnseenCompletion:
        cell.task !== undefined &&
        hasUnseenCompletion(
          cell.status,
          taskActivityAt(cell.task),
          timestamps[cell.task.id],
        ),
    }));
  }, [storeCells, taskById, sessionByTaskId, workspaces, timestamps]);

  const summary = useMemo(() => buildStatusSummary(cells), [cells]);

  return { cells, summary };
}

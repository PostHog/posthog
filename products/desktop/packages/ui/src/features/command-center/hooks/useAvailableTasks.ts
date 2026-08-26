import {
  selectAvailableTasks,
  workspaceIdSet,
} from "@posthog/core/command-center/eligibility";
import type { Task } from "@posthog/shared/domain-types";
import { useMemo } from "react";
import { useArchivedTaskIds } from "../../archive/useArchivedTaskIds";
import { useTasks } from "../../tasks/useTasks";
import { useWorkspaces } from "../../workspace/useWorkspace";
import { useCommandCenterStore } from "../commandCenterStore";

export function useAvailableTasks(): Task[] {
  const { data: tasks = [] } = useTasks();
  const cells = useCommandCenterStore((s) => s.cells);
  const archivedTaskIds = useArchivedTaskIds();
  const { data: workspaces } = useWorkspaces();

  return useMemo(() => {
    const assignedIds = new Set(cells.filter((id): id is string => id != null));
    return selectAvailableTasks(tasks, {
      assignedIds,
      archivedIds: archivedTaskIds,
      workspaceIds: workspaceIdSet(workspaces),
    });
  }, [tasks, cells, archivedTaskIds, workspaces]);
}

import { selectAutofillCandidates } from "@posthog/core/command-center/autofill";
import { workspaceIdSet } from "@posthog/core/command-center/eligibility";
import { useEffect } from "react";
import { useArchivedTaskIds } from "../../archive/useArchivedTaskIds";
import { useTasks } from "../../tasks/useTasks";
import { useWorkspaces } from "../../workspace/useWorkspace";
import { useCommandCenterStore } from "../commandCenterStore";

export function useAutofillCommandCenter(): void {
  const { data: tasks = [], isFetched: tasksFetched } = useTasks();
  const { data: workspaces, isFetched: workspacesFetched } = useWorkspaces();
  const archivedTaskIds = useArchivedTaskIds();

  const cells = useCommandCenterStore((s) => s.cells);
  const hasAutofilled = useCommandCenterStore((s) => s.hasAutofilled);
  const autofillCells = useCommandCenterStore((s) => s.autofillCells);

  useEffect(() => {
    // One-time bootstrap: the persisted `hasAutofilled` flag stops empty cells
    // from being re-filled every time the Command Center remounts.
    if (hasAutofilled) return;
    if (!workspacesFetched || !workspaces) return;
    if (!tasksFetched) return;

    const emptySlots = cells.filter((id) => id == null).length;
    const assignedIds = new Set(cells.filter((id): id is string => id != null));
    const candidates = selectAutofillCandidates(tasks, {
      assignedIds,
      archivedIds: archivedTaskIds,
      workspaceIds: workspaceIdSet(workspaces),
      emptySlots,
      nowMs: Date.now(),
    });

    autofillCells(candidates);
  }, [
    cells,
    hasAutofilled,
    workspaces,
    workspacesFetched,
    tasks,
    tasksFetched,
    archivedTaskIds,
    autofillCells,
  ]);
}

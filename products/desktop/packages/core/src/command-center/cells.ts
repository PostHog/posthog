import type { AgentSession, WorkspaceMode } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import {
  getTerminalCellCwd,
  getTerminalCellId,
  isBrainrotCell,
  isTerminalCell,
} from "./grid";
import { type CellStatus, deriveStatus, getRepoName } from "./status";

export interface CommandCenterCellData {
  cellIndex: number;
  taskId: string | null;
  task: Task | undefined;
  session: AgentSession | undefined;
  status: CellStatus;
  repoName: string | null;
  workspaceMode: WorkspaceMode | null;
  // Brainrot: a looping video slot rather than a task.
  isBrainrot: boolean;
  // Standalone terminal slot, independent of any agent run.
  terminalId: string | null;
  terminalCwd: string | null;
}

export interface BuildCellsInput {
  taskById: Map<string, Task>;
  sessionByTaskId: Map<string, AgentSession>;
  workspaces: Record<string, { mode: WorkspaceMode } | undefined> | undefined;
}

const EMPTY_CELL_DATA = {
  taskId: null,
  task: undefined,
  session: undefined,
  status: "idle" as const,
  repoName: null,
  workspaceMode: null,
  isBrainrot: false,
  terminalId: null,
  terminalCwd: null,
};

export function buildCommandCenterCells(
  storeCells: (string | null)[],
  input: BuildCellsInput,
): CommandCenterCellData[] {
  const { taskById, sessionByTaskId, workspaces } = input;
  return storeCells.map((cellValue, cellIndex) => {
    if (isBrainrotCell(cellValue)) {
      return { ...EMPTY_CELL_DATA, cellIndex, isBrainrot: true };
    }

    if (isTerminalCell(cellValue)) {
      return {
        ...EMPTY_CELL_DATA,
        cellIndex,
        terminalId: getTerminalCellId(cellValue),
        terminalCwd: getTerminalCellCwd(cellValue),
      };
    }

    const taskId = cellValue;
    const task = taskId ? taskById.get(taskId) : undefined;
    const session = taskId ? sessionByTaskId.get(taskId) : undefined;
    const status = taskId ? deriveStatus(session) : "idle";
    const repoName = task ? getRepoName(task) : null;
    const workspaceMode = (taskId ? workspaces?.[taskId]?.mode : null) ?? null;

    return {
      ...EMPTY_CELL_DATA,
      cellIndex,
      taskId,
      task,
      session,
      status,
      repoName,
      workspaceMode,
    };
  });
}

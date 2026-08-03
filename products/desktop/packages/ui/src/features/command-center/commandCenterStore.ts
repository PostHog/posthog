import {
  BRAINROT_CELL,
  clampZoom,
  getCellCount,
  type LayoutPreset,
  makeTerminalCellValue,
  resizeCells,
  ZOOM_STEP,
} from "@posthog/core/command-center/grid";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type { LayoutPreset } from "@posthog/core/command-center/grid";
export {
  getCellSessionId,
  getGridDimensions,
} from "@posthog/core/command-center/grid";

interface CommandCenterStoreState {
  layout: LayoutPreset;
  cells: (string | null)[];
  activeTaskId: string | null;
  activeCellIndex: number | null;
  zoom: number;
  creatingCells: number[];
  // Persisted so autofill bootstraps the grid only once, not on every remount.
  hasAutofilled: boolean;
}

interface CommandCenterStoreActions {
  setLayout: (preset: LayoutPreset) => void;
  setActiveTask: (taskId: string | null) => void;
  setActiveCell: (cellIndex: number | null) => void;
  assignTask: (cellIndex: number, taskId: string) => void;
  setBrainrotCell: (cellIndex: number) => void;
  setTerminalCell: (
    cellIndex: number,
    terminalId: string,
    cwd?: string,
  ) => void;
  autofillCells: (taskIds: string[]) => void;
  clearCell: (cellIndex: number) => void;
  removeTaskById: (taskId: string) => void;
  clearAll: () => void;
  setZoom: (zoom: number) => void;
  zoomIn: () => void;
  zoomOut: () => void;
  startCreating: (cellIndex: number) => void;
  stopCreating: (cellIndex: number) => void;
}

export const COMMAND_CENTER_INITIAL_STATE: CommandCenterStoreState = {
  layout: "2x2",
  cells: [null, null, null, null],
  activeTaskId: null,
  activeCellIndex: null,
  zoom: 1,
  creatingCells: [],
  hasAutofilled: false,
};

type CommandCenterStore = CommandCenterStoreState & CommandCenterStoreActions;

export const useCommandCenterStore = create<CommandCenterStore>()(
  persist(
    (set) => ({
      ...COMMAND_CENTER_INITIAL_STATE,

      setLayout: (preset) =>
        set((state) => {
          const newCount = getCellCount(preset);
          return {
            activeTaskId: resizeCells(state.cells, newCount).includes(
              state.activeTaskId,
            )
              ? state.activeTaskId
              : null,
            activeCellIndex:
              state.activeCellIndex !== null && state.activeCellIndex < newCount
                ? state.activeCellIndex
                : null,
            layout: preset,
            cells: resizeCells(state.cells, newCount),
            creatingCells: state.creatingCells.filter((i) => i < newCount),
          };
        }),

      setActiveTask: (taskId) => set({ activeTaskId: taskId }),

      setActiveCell: (cellIndex) => set({ activeCellIndex: cellIndex }),

      assignTask: (cellIndex, taskId) =>
        set((state) => {
          if (cellIndex < 0 || cellIndex >= state.cells.length) return state;
          const cells = [...state.cells];
          const existingIndex = cells.indexOf(taskId);
          if (existingIndex !== -1) {
            cells[existingIndex] = null;
          }
          cells[cellIndex] = taskId;
          return {
            cells,
            activeTaskId: taskId,
            creatingCells: state.creatingCells.filter((i) => i !== cellIndex),
            // Manually placing a task counts as curating the grid.
            hasAutofilled: true,
          };
        }),

      setBrainrotCell: (cellIndex) =>
        set((state) => {
          if (cellIndex < 0 || cellIndex >= state.cells.length) return state;
          const cells = [...state.cells];
          cells[cellIndex] = BRAINROT_CELL;
          return {
            cells,
            activeTaskId: null,
            activeCellIndex: cellIndex,
            creatingCells: state.creatingCells.filter((i) => i !== cellIndex),
            hasAutofilled: true,
          };
        }),

      setTerminalCell: (cellIndex, terminalId, cwd) =>
        set((state) => {
          if (cellIndex < 0 || cellIndex >= state.cells.length) return state;
          const cells = [...state.cells];
          cells[cellIndex] = makeTerminalCellValue(terminalId, cwd);
          return {
            cells,
            activeTaskId: null,
            activeCellIndex: cellIndex,
            creatingCells: state.creatingCells.filter((i) => i !== cellIndex),
            hasAutofilled: true,
          };
        }),

      autofillCells: (taskIds) =>
        set((state) => {
          // Grid already full: nothing to place, but the bootstrap is done.
          if (state.cells.every((id) => id != null)) {
            return { hasAutofilled: true };
          }
          if (taskIds.length === 0) return state;
          const cells: (string | null)[] = [...state.cells];
          const queue = [...taskIds];
          for (let i = 0; i < cells.length && queue.length > 0; i++) {
            if (cells[i] == null) {
              cells[i] = queue.shift() as string;
            }
          }
          return { cells, hasAutofilled: true };
        }),

      clearCell: (cellIndex) =>
        set((state) => {
          const cells = [...state.cells];
          const removedTaskId = cells[cellIndex];
          cells[cellIndex] = null;
          return {
            cells,
            activeTaskId:
              removedTaskId && state.activeTaskId === removedTaskId
                ? null
                : state.activeTaskId,
          };
        }),

      removeTaskById: (taskId) =>
        set((state) => {
          const index = state.cells.indexOf(taskId);
          if (index === -1) return state;
          const cells = [...state.cells];
          cells[index] = null;
          return {
            cells,
            activeTaskId:
              state.activeTaskId === taskId ? null : state.activeTaskId,
          };
        }),

      clearAll: () =>
        set((state) => ({
          activeTaskId: null,
          activeCellIndex: null,
          cells: state.cells.map(() => null),
          creatingCells: [],
        })),

      setZoom: (zoom) => set({ zoom: clampZoom(zoom) }),
      zoomIn: () =>
        set((state) => ({ zoom: clampZoom(state.zoom + ZOOM_STEP) })),
      zoomOut: () =>
        set((state) => ({ zoom: clampZoom(state.zoom - ZOOM_STEP) })),

      startCreating: (cellIndex) =>
        set((state) => ({
          creatingCells: state.creatingCells.includes(cellIndex)
            ? state.creatingCells
            : [...state.creatingCells, cellIndex],
        })),

      stopCreating: (cellIndex) =>
        set((state) => ({
          creatingCells: state.creatingCells.filter((i) => i !== cellIndex),
        })),
    }),
    {
      name: "command-center-storage",
      storage: electronStorage,
      partialize: (state) => ({
        layout: state.layout,
        cells: state.cells,
        activeTaskId: state.activeTaskId,
        activeCellIndex: state.activeCellIndex,
        zoom: state.zoom,
        creatingCells: state.creatingCells,
        hasAutofilled: state.hasAutofilled,
      }),
    },
  ),
);

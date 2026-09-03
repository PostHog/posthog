import type { CanvasV2Viewport } from "@posthog/shared";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export const DEFAULT_BOARD_VIEWPORT: CanvasV2Viewport = { x: 0, y: 0, zoom: 1 };

interface BoardLocalState {
  viewport: CanvasV2Viewport;
  /** The chat session this person opened for the board. Never in the op log. */
  taskId?: string;
}

interface BoardViewportState {
  boards: Record<string, BoardLocalState>;
  setViewport: (boardId: string, viewport: CanvasV2Viewport) => void;
  setTaskForBoard: (boardId: string, taskId: string | undefined) => void;
}

/**
 * Where each board sits on this device, and which session is open beside it.
 * Both facts are per person: a collaborator must not move your view.
 */
export const useBoardViewportStore = create<BoardViewportState>()(
  persist(
    (set) => ({
      boards: {},
      setViewport: (boardId, viewport) => {
        set((state) => ({
          boards: {
            ...state.boards,
            [boardId]: { ...state.boards[boardId], viewport },
          },
        }));
      },
      setTaskForBoard: (boardId, taskId) => {
        set((state) => ({
          boards: {
            ...state.boards,
            [boardId]: {
              viewport:
                state.boards[boardId]?.viewport ?? DEFAULT_BOARD_VIEWPORT,
              taskId,
            },
          },
        }));
      },
    }),
    {
      name: "posthog-code-canvas-v2-viewports",
      storage: electronStorage,
      partialize: (state) => ({ boards: state.boards }),
    },
  ),
);

export function useBoardViewport(boardId: string): CanvasV2Viewport {
  return useBoardViewportStore(
    (state) => state.boards[boardId]?.viewport ?? DEFAULT_BOARD_VIEWPORT,
  );
}

export function useBoardTaskId(boardId: string): string | undefined {
  return useBoardViewportStore((state) => state.boards[boardId]?.taskId);
}

/** Non-React writer, for the task-creation callback. */
export function setTaskForBoard(
  boardId: string,
  taskId: string | undefined,
): void {
  useBoardViewportStore.getState().setTaskForBoard(boardId, taskId);
}

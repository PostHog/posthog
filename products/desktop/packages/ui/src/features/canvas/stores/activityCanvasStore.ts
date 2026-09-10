import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Which canvas draws the activity panel's Canvas tab. One choice per person,
 * not one per task: the tab answers "how do I want to read activity", and a
 * per-task choice would make every new session start over.
 */
interface ActivityCanvasState {
  canvasId: string | null;
  setCanvasId: (canvasId: string | null) => void;
}

export const useActivityCanvasStore = create<ActivityCanvasState>()(
  persist(
    (set) => ({
      canvasId: null,
      setCanvasId: (canvasId) => set({ canvasId }),
    }),
    { name: "activity-canvas-storage", storage: electronStorage },
  ),
);

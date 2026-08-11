import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// How a space's artifacts are laid out. "list" is the dense row list, "grid" a
// uniform card grid with live canvas previews, "masonry" the same cards in
// staggered columns so previews get varied vertical room.
export type ArtifactsViewMode = "list" | "grid" | "masonry";

export const ARTIFACTS_VIEW_MODES: ArtifactsViewMode[] = [
  "list",
  "grid",
  "masonry",
];

interface ArtifactsViewStore {
  view: ArtifactsViewMode;
  setView: (view: ArtifactsViewMode, channelId?: string) => void;
}

// Per-device preference, not per-space: picking masonry once should hold as you
// move between spaces, the way a file browser's view setting does.
export const useArtifactsViewStore = create<ArtifactsViewStore>()(
  persist(
    (set) => ({
      view: "list",
      setView: (view, channelId) =>
        set((state) => {
          if (state.view === view) return state;
          track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
            action_type: "artifacts_view_change",
            surface: "channel_artifacts",
            channel_id: channelId,
            view_mode: view,
          });
          return { view };
        }),
    }),
    { name: "artifacts-view-storage" },
  ),
);

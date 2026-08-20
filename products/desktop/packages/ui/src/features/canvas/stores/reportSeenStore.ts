import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// The Slack-style read stamp for a space's reports: per report-view key
// (channel id, or "general"), the newest report arrival the user has looked
// at. The unread badge counts reports newer than the stamp; looking at a
// Reports surface advances it. Local-only, like channelSeenStore — the server
// has no per-user read state for reports.
interface ReportSeenState {
  seenAtByView: Record<string, string>;
  /** False until the persisted map is back from storage — see `merge` below. */
  hasHydrated: boolean;
  markReportsSeen: (viewKey: string, at: string) => void;
}

/** Keep whichever stamp is later, so a stamp is never walked backwards. */
function latestSeen(
  a: Record<string, string>,
  b: Record<string, string>,
): Record<string, string> {
  const merged = { ...a };
  for (const [viewKey, at] of Object.entries(b)) {
    const current = merged[viewKey];
    if (!current || at > current) merged[viewKey] = at;
  }
  return merged;
}

export const useReportSeenStore = create<ReportSeenState>()(
  persist(
    (set) => ({
      seenAtByView: {},
      hasHydrated: false,
      markReportsSeen: (viewKey, at) =>
        set((state) => {
          const current = state.seenAtByView[viewKey];
          if (current && current >= at) return state;
          return { seenAtByView: { ...state.seenAtByView, [viewKey]: at } };
        }),
    }),
    {
      name: "reports-seen",
      storage: electronStorage,
      partialize: (state) => ({ seenAtByView: state.seenAtByView }),
      // Storage is async (IPC), so a surface viewed during boot can stamp
      // itself seen before the persisted map arrives; fold the two and keep
      // the later stamp per view (same rationale as channelSeenStore).
      merge: (persisted, current) => ({
        ...current,
        seenAtByView: latestSeen(
          current.seenAtByView,
          (persisted as Partial<ReportSeenState> | undefined)?.seenAtByView ??
            {},
        ),
      }),
      onRehydrateStorage: () => () => {
        useReportSeenStore.setState({ hasHydrated: true });
      },
    },
  ),
);

export function reportViewKey(view: {
  kind: "general" | "channel";
  channelId?: string;
}): string {
  return view.kind === "channel" && view.channelId ? view.channelId : "general";
}

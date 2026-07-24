import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// When the viewer last had each channel open, keyed by backend channel id.
// Activity newer than this bolds the channel in the sidebar; opening the
// channel clears it. Per-channel (unlike the Activity page's single
// `lastSeenAt`) so reading one channel doesn't mark every other one read.
interface ChannelSeenState {
  lastSeenByChannel: Record<string, string>;
  /** False until the persisted map is back from storage — see `merge` below. */
  hasHydrated: boolean;
  markChannelSeen: (channelId: string, at: string) => void;
}

/** Keep whichever visit is later, so a stamp is never walked backwards. */
function latestSeen(
  a: Record<string, string>,
  b: Record<string, string>,
): Record<string, string> {
  const merged = { ...a };
  for (const [channelId, at] of Object.entries(b)) {
    const current = merged[channelId];
    if (!current || at > current) merged[channelId] = at;
  }
  return merged;
}

export const useChannelSeenStore = create<ChannelSeenState>()(
  persist(
    (set) => ({
      lastSeenByChannel: {},
      hasHydrated: false,
      markChannelSeen: (channelId, at) =>
        set((state) => {
          // A channel visited after its newest activity is read; re-stamping it
          // with an older mention would bold it again.
          const current = state.lastSeenByChannel[channelId];
          if (current && current >= at) return state;
          return {
            lastSeenByChannel: { ...state.lastSeenByChannel, [channelId]: at },
          };
        }),
    }),
    {
      name: "channels-seen",
      storage: electronStorage,
      partialize: (state) => ({ lastSeenByChannel: state.lastSeenByChannel }),
      // Storage is async (IPC), so a channel opened during boot can stamp
      // itself seen before the persisted map arrives. zustand's default merge
      // would then replace that stamp with what was on disk and lose it, so
      // fold the two together instead and keep the later visit per channel.
      merge: (persisted, current) => ({
        ...current,
        lastSeenByChannel: latestSeen(
          current.lastSeenByChannel,
          (persisted as Partial<ChannelSeenState>)?.lastSeenByChannel ?? {},
        ),
      }),
      onRehydrateStorage: () => (state) => {
        // Readers gate on this: before it flips, an empty map is
        // indistinguishable from "nothing has ever been read", which would
        // bold every channel that has any activity.
        useChannelSeenStore.setState({ hasHydrated: true });
        return state;
      },
    },
  ),
);

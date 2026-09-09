import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ChannelIntroState {
  dismissedByChannel: Record<string, true>;
  dismissIntro: (channelId: string) => void;
}

// Which channels' feed intro (welcome + onboarding card) the user has closed.
// Per-device on purpose: the intro is orientation, not shared channel state.
export const useChannelIntroStore = create<ChannelIntroState>()(
  persist(
    (set) => ({
      dismissedByChannel: {},
      dismissIntro: (channelId) =>
        set((state) => ({
          dismissedByChannel: {
            ...state.dismissedByChannel,
            [channelId]: true,
          },
        })),
    }),
    {
      name: "channel-intro-storage",
      storage: electronStorage,
    },
  ),
);

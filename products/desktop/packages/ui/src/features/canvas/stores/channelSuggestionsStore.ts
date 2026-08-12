import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ChannelSuggestionsStore {
  suggestionsVisible: boolean;
  setSuggestionsVisible: (suggestionsVisible: boolean) => void;
}

export const useChannelSuggestionsStore = create<ChannelSuggestionsStore>()(
  persist(
    (set) => ({
      suggestionsVisible: true,
      setSuggestionsVisible: (suggestionsVisible) =>
        set({ suggestionsVisible }),
    }),
    { name: "channel-suggestions" },
  ),
);

import { create } from "zustand";

interface CurrentChannelState {
  currentChannelId: string | null;
  setCurrentChannel: (channelId: string | null) => void;
}

export const useCurrentChannelStore = create<CurrentChannelState>()((set) => ({
  currentChannelId: null,
  setCurrentChannel: (currentChannelId) => set({ currentChannelId }),
}));

export function resetCurrentChannel(): void {
  useCurrentChannelStore.setState({ currentChannelId: null });
}

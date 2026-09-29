import { create } from "zustand";

export const useSpace = create<{
  channelId: string | null;
  setChannelId: (channelId: string | null) => void;
}>((set) => ({
  channelId: null,
  setChannelId: (channelId) => set({ channelId }),
}));

import { createStore } from "zustand/vanilla";

interface ConnectivityState {
  isOnline: boolean;
  setOnline: (isOnline: boolean) => void;
}

export const connectivityStore = createStore<ConnectivityState>((set) => ({
  isOnline: true,
  setOnline: (isOnline) => set({ isOnline }),
}));

export const getIsOnline = () => connectivityStore.getState().isOnline;

import type { CloudRegion } from "@posthog/shared";
import { create } from "zustand";

interface AuthUiStateStoreState {
  authMode: "login" | "signup";
  selectedRegion: CloudRegion | null;
  staleRegion: CloudRegion | null;
}

interface AuthUiStateStoreActions {
  setAuthMode: (mode: "login" | "signup") => void;
  setSelectedRegion: (region: CloudRegion | null) => void;
  setStaleRegion: (region: CloudRegion | null) => void;
  clearStaleRegion: () => void;
}

type AuthUiStateStore = AuthUiStateStoreState & AuthUiStateStoreActions;

export const useAuthUiStateStore = create<AuthUiStateStore>((set) => ({
  authMode: "login",
  selectedRegion: null,
  staleRegion: null,

  setAuthMode: (authMode) => set({ authMode }),
  setSelectedRegion: (selectedRegion) => set({ selectedRegion }),
  setStaleRegion: (region) => set({ staleRegion: region }),
  clearStaleRegion: () => set({ staleRegion: null }),
}));

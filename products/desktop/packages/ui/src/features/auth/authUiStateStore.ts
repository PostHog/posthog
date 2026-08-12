import type { CloudRegion } from "@posthog/shared";
import { create } from "zustand";

interface AuthUiStateStoreState {
  authMode: "login" | "signup";
  inviteCode: string;
  selectedRegion: CloudRegion | null;
  staleRegion: CloudRegion | null;
}

interface AuthUiStateStoreActions {
  setAuthMode: (mode: "login" | "signup") => void;
  setInviteCode: (inviteCode: string) => void;
  resetInviteCode: () => void;
  setSelectedRegion: (region: CloudRegion | null) => void;
  setStaleRegion: (region: CloudRegion | null) => void;
  clearStaleRegion: () => void;
}

type AuthUiStateStore = AuthUiStateStoreState & AuthUiStateStoreActions;

export const useAuthUiStateStore = create<AuthUiStateStore>((set) => ({
  authMode: "login",
  inviteCode: "",
  selectedRegion: null,
  staleRegion: null,

  setAuthMode: (authMode) => set({ authMode }),
  setInviteCode: (inviteCode) => set({ inviteCode }),
  resetInviteCode: () => set({ inviteCode: "" }),
  setSelectedRegion: (selectedRegion) => set({ selectedRegion }),
  setStaleRegion: (region) => set({ staleRegion: region }),
  clearStaleRegion: () => set({ staleRegion: null }),
}));

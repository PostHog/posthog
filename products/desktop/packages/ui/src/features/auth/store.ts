import { getAuthIdentity } from "@posthog/core/auth/authIdentity";
import type { AuthState } from "@posthog/core/auth/schemas";
import { create } from "zustand";

export { getAuthIdentity };

export const ANONYMOUS_AUTH_STATE: AuthState = {
  status: "anonymous",
  bootstrapComplete: false,
  cloudRegion: null,
  orgProjectsMap: {},
  currentOrgId: null,
  currentProjectId: null,
  hasCodeAccess: null,
  needsScopeReauth: false,
};

interface AuthStoreState {
  authState: AuthState;
  setAuthState: (state: AuthState) => void;
}

export const useAuthStore = create<AuthStoreState>((set) => ({
  authState: ANONYMOUS_AUTH_STATE,
  setAuthState: (authState) => set({ authState }),
}));

export function useAuthState(): AuthState {
  return useAuthStore((s) => s.authState);
}

export function useAuthStateValue<T>(selector: (state: AuthState) => T): T {
  return useAuthStore((s) => selector(s.authState));
}

export function useAuthStateFetched(): boolean {
  return useAuthStore((s) => s.authState.bootstrapComplete);
}

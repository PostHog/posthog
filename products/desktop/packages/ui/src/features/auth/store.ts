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
  desktopAccess: { projectId: null, status: "unchecked", reason: null },
  needsScopeReauth: false,
  sessionType: null,
  sessionExpiresAt: null,
  sessionEndReason: null,
};

interface AuthStoreState {
  authState: AuthState;
  setAuthState: (state: AuthState) => void;
}

export const useAuthStore = create<AuthStoreState>((set) => ({
  authState: ANONYMOUS_AUTH_STATE,
  setAuthState: (authState) => set({ authState }),
}));

export function syncSharedAuthState(incoming: AuthState): void {
  const current = useAuthStore.getState().authState;
  const currentProjectId = current.currentProjectId;
  const currentProjectStillAvailable = Object.values(
    incoming.orgProjectsMap,
  ).some((org) =>
    org.projects.some((project) => project.id === currentProjectId),
  );

  if (
    current.status === "authenticated" &&
    incoming.status === "authenticated" &&
    current.cloudRegion === incoming.cloudRegion &&
    currentProjectId !== null &&
    currentProjectStillAvailable
  ) {
    const currentOrgId = Object.entries(incoming.orgProjectsMap).find(
      ([, org]) =>
        org.projects.some((project) => project.id === currentProjectId),
    )?.[0];
    useAuthStore.getState().setAuthState({
      ...incoming,
      currentOrgId: currentOrgId ?? current.currentOrgId,
      currentProjectId,
      desktopAccess: current.desktopAccess,
    });
    return;
  }

  useAuthStore.getState().setAuthState(incoming);
}

export function useAuthState(): AuthState {
  return useAuthStore((s) => s.authState);
}

export function useAuthStateValue<T>(selector: (state: AuthState) => T): T {
  return useAuthStore((s) => selector(s.authState));
}

export function useAuthStateFetched(): boolean {
  return useAuthStore((s) => s.authState.bootstrapComplete);
}

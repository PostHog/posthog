import type { AuthState } from "./schemas";

export function getAuthIdentity(authState: AuthState): string | null {
  if (authState.status !== "authenticated" || !authState.cloudRegion) {
    return null;
  }
  return `${authState.cloudRegion}:${authState.currentProjectId ?? "none"}`;
}

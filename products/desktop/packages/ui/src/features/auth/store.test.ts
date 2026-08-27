import type { AuthState } from "@posthog/core/auth/schemas";
import { beforeEach, describe, expect, it } from "vitest";
import {
  ANONYMOUS_AUTH_STATE,
  syncSharedAuthState,
  useAuthStore,
} from "./store";

function authenticatedState(projectId: number): AuthState {
  return {
    ...ANONYMOUS_AUTH_STATE,
    status: "authenticated",
    bootstrapComplete: true,
    cloudRegion: "us",
    currentOrgId: "org-1",
    currentProjectId: projectId,
    orgProjectsMap: {
      "org-1": {
        orgName: "Example",
        projects: [
          { id: 1, name: "One" },
          { id: 2, name: "Two" },
        ],
      },
    },
    desktopAccess: { projectId, status: "allowed", reason: null },
    sessionType: "persistent",
  };
}

describe("syncSharedAuthState", () => {
  beforeEach(() => {
    useAuthStore.getState().setAuthState(ANONYMOUS_AUTH_STATE);
  });

  it("keeps this window's project when another window selects a project", () => {
    useAuthStore.getState().setAuthState(authenticatedState(1));

    syncSharedAuthState(authenticatedState(2));

    expect(useAuthStore.getState().authState.currentProjectId).toBe(1);
  });

  it("still applies shared logout state", () => {
    useAuthStore.getState().setAuthState(authenticatedState(1));

    syncSharedAuthState({
      ...ANONYMOUS_AUTH_STATE,
      bootstrapComplete: true,
      cloudRegion: "us",
    });

    expect(useAuthStore.getState().authState.status).toBe("anonymous");
    expect(useAuthStore.getState().authState.currentProjectId).toBeNull();
  });
});

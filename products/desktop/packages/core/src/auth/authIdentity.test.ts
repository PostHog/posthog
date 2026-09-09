import { configureCustomCloud } from "@posthog/shared";
import { afterEach, describe, expect, it } from "vitest";
import type { AuthState } from "./schemas";
import { getAuthIdentity } from "./authIdentity";

function authState(overrides: Partial<AuthState>): AuthState {
  return {
    status: "authenticated",
    bootstrapComplete: true,
    cloudRegion: "us",
    orgProjectsMap: {},
    currentOrgId: null,
    currentProjectId: 1,
    desktopAccess: { projectId: 1, status: "allowed", reason: null },
    needsScopeReauth: false,
    sessionType: "persistent",
    sessionExpiresAt: null,
    sessionEndReason: undefined,
    ...overrides,
  };
}

describe("getAuthIdentity", () => {
  afterEach(() => {
    configureCustomCloud(null);
  });

  it("names the region and the project for a built-in region", () => {
    expect(getAuthIdentity(authState({ cloudRegion: "eu" }))).toBe("eu:1");
  });

  it("returns null when signed out", () => {
    expect(
      getAuthIdentity(authState({ status: "anonymous", cloudRegion: null })),
    ).toBeNull();
  });

  it("names the custom instance, so two instances never share an identity", () => {
    configureCustomCloud({
      url: "https://posthog.example.com",
      oauthClientId: "client-id",
    });
    expect(getAuthIdentity(authState({ cloudRegion: "custom" }))).toBe(
      "custom:posthog.example.com:1",
    );

    configureCustomCloud({
      url: "https://other.example.com",
      oauthClientId: "client-id",
    });
    expect(getAuthIdentity(authState({ cloudRegion: "custom" }))).toBe(
      "custom:other.example.com:1",
    );
  });
});

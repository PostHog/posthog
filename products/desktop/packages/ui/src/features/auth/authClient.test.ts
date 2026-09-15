import { registerApiBaseHost } from "@posthog/ui/shell/apiBaseHostRegistry";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createAuthenticatedClient } from "./authClient";
import { ANONYMOUS_AUTH_STATE } from "./store";

vi.mock("@posthog/api-client/posthog-client", () => ({
  PostHogAPIClient: vi.fn(function PostHogAPIClient() {
    return { setTeamId: vi.fn() };
  }),
}));

vi.mock("@posthog/ui/shell/apiBaseHostRegistry", () => ({
  registerApiBaseHost: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe("createAuthenticatedClient", () => {
  it("registers the region's backend host", () => {
    createAuthenticatedClient(
      { ...ANONYMOUS_AUTH_STATE, status: "authenticated", cloudRegion: "us" },
      vi.fn(),
      vi.fn(),
    );

    expect(registerApiBaseHost).toHaveBeenCalledWith("https://us.posthog.com");
  });

  it("does not register a host without an authenticated session", () => {
    createAuthenticatedClient(ANONYMOUS_AUTH_STATE, vi.fn(), vi.fn());

    expect(registerApiBaseHost).not.toHaveBeenCalled();
  });
});

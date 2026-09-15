import { registerApiBaseHost } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createAuthenticatedClient } from "./authClient";
import { ANONYMOUS_AUTH_STATE } from "./store";

vi.mock("@posthog/api-client/posthog-client", () => ({
  PostHogAPIClient: vi.fn(function PostHogAPIClient() {
    return { setTeamId: vi.fn() };
  }),
}));

vi.mock("@posthog/ui/shell/posthogAnalyticsImpl", () => ({
  registerApiBaseHost: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

// registerApiBaseHost's value is what lets the network-duration metric (see
// posthogAnalyticsImpl.networkMetricPath) recognize the app's own requests. A
// build-time env var can't carry it: the backend host is only known once the
// user's cloud region is, which happens here.
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

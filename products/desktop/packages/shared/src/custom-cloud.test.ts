import { afterEach, describe, expect, it, vi } from "vitest";
import { getCustomCloud, hasCustomCloud } from "./custom-cloud";

describe("getCustomCloud", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("reads the three values and removes the trailing slash", () => {
    vi.stubEnv("POSTHOG_CUSTOM_CLOUD_URL", "https://posthog.example.com/");
    vi.stubEnv("POSTHOG_CUSTOM_CLOUD_OAUTH_CLIENT_ID", "custom-client-id");
    vi.stubEnv(
      "POSTHOG_CUSTOM_CLOUD_GATEWAY_URL",
      "https://gateway.example.com",
    );
    expect(getCustomCloud()).toEqual({
      url: "https://posthog.example.com",
      oauthClientId: "custom-client-id",
      gatewayUrl: "https://gateway.example.com",
    });
    expect(hasCustomCloud()).toBe(true);
  });

  it.each([
    { name: "an empty value", url: "  " },
    { name: "a scheme that is not http", url: "file:///etc/passwd" },
    { name: "a value that is not a URL", url: "posthog.example.com" },
  ])("returns null for $name", ({ url }) => {
    vi.stubEnv("POSTHOG_CUSTOM_CLOUD_URL", url);
    expect(getCustomCloud()).toBeNull();
    expect(hasCustomCloud()).toBe(false);
  });

  it("drops a gateway URL that is not http", () => {
    vi.stubEnv("POSTHOG_CUSTOM_CLOUD_URL", "https://posthog.example.com");
    vi.stubEnv("POSTHOG_CUSTOM_CLOUD_GATEWAY_URL", "ftp://gateway.example.com");
    expect(getCustomCloud()?.gatewayUrl).toBeUndefined();
  });
});

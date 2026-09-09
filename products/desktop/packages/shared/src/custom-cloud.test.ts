import { afterEach, describe, expect, it, vi } from "vitest";
import {
  configureCustomCloud,
  customCloudGatewayToken,
  getCustomCloud,
  hasCustomCloud,
  normalizeCustomCloud,
} from "./custom-cloud";

describe("custom cloud", () => {
  afterEach(() => {
    configureCustomCloud(null);
    vi.unstubAllEnvs();
  });

  describe("normalizeCustomCloud", () => {
    it("trims the values and removes the trailing slash", () => {
      expect(
        normalizeCustomCloud({
          url: " https://posthog.example.com/ ",
          oauthClientId: " custom-client-id ",
          gatewayUrl: "https://gateway.example.com/",
        }),
      ).toEqual({
        url: "https://posthog.example.com",
        oauthClientId: "custom-client-id",
        gatewayUrl: "https://gateway.example.com",
      });
    });

    it.each([
      { name: "no input", input: null },
      { name: "an empty URL", input: { url: "  " } },
      {
        name: "a scheme that is not http",
        input: { url: "file:///etc/passwd" },
      },
      {
        name: "a value that is not a URL",
        input: { url: "posthog.example.com" },
      },
    ])("returns null for $name", ({ input }) => {
      expect(normalizeCustomCloud(input)).toBeNull();
    });

    it("drops a gateway URL that is not http", () => {
      expect(
        normalizeCustomCloud({
          url: "https://posthog.example.com",
          gatewayUrl: "ftp://gateway.example.com",
        })?.gatewayUrl,
      ).toBeUndefined();
    });
  });

  describe("getCustomCloud", () => {
    it("prefers the configured target over the environment", () => {
      vi.stubEnv("POSTHOG_CUSTOM_CLOUD_URL", "https://from-env.example.com");
      configureCustomCloud({ url: "https://configured.example.com" });
      expect(getCustomCloud()?.url).toBe("https://configured.example.com");
    });

    it("falls back to the environment when nothing is configured", () => {
      vi.stubEnv("POSTHOG_CUSTOM_CLOUD_URL", "https://from-env.example.com");
      vi.stubEnv("POSTHOG_CUSTOM_CLOUD_OAUTH_CLIENT_ID", "env-client-id");
      expect(getCustomCloud()).toEqual({
        url: "https://from-env.example.com",
        oauthClientId: "env-client-id",
        gatewayUrl: undefined,
      });
      expect(hasCustomCloud()).toBe(true);
    });
  });

  describe("customCloudGatewayToken", () => {
    it("returns the token for the custom host only", () => {
      configureCustomCloud({
        url: "https://posthog.example.com",
        gatewayToken: "phx_custom",
      });
      expect(customCloudGatewayToken("https://posthog.example.com/")).toBe(
        "phx_custom",
      );
      expect(customCloudGatewayToken("https://us.posthog.com")).toBeUndefined();
    });

    it("returns nothing when the custom cloud has no token", () => {
      configureCustomCloud({ url: "https://posthog.example.com" });
      expect(
        customCloudGatewayToken("https://posthog.example.com"),
      ).toBeUndefined();
    });
  });
});

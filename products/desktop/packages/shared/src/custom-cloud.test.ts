import { afterEach, describe, expect, it, vi } from "vitest";
import {
  configureCustomCloud,
  getCustomCloud,
  hasCustomCloud,
  readCustomCloudFromEnv,
} from "./custom-cloud";

describe("custom cloud", () => {
  afterEach(() => {
    configureCustomCloud(null);
    vi.unstubAllEnvs();
  });

  describe("readCustomCloudFromEnv", () => {
    it("reads the three values and removes the trailing slash", () => {
      expect(
        readCustomCloudFromEnv({
          POSTHOG_CUSTOM_CLOUD_URL: "https://posthog.example.com/",
          POSTHOG_CUSTOM_CLOUD_OAUTH_CLIENT_ID: "custom-client-id",
          POSTHOG_CUSTOM_CLOUD_GATEWAY_URL: "https://gateway.example.com",
        }),
      ).toEqual({
        url: "https://posthog.example.com",
        oauthClientId: "custom-client-id",
        gatewayUrl: "https://gateway.example.com",
      });
    });

    it("accepts the build-time name when the plain name is absent", () => {
      expect(
        readCustomCloudFromEnv({
          VITE_POSTHOG_CUSTOM_CLOUD_URL: "http://posthog.example.com:8000",
        })?.url,
      ).toBe("http://posthog.example.com:8000");
    });

    it.each([
      { name: "no value", env: {} },
      { name: "an empty value", env: { POSTHOG_CUSTOM_CLOUD_URL: "  " } },
      {
        name: "a scheme that is not http",
        env: { POSTHOG_CUSTOM_CLOUD_URL: "file:///etc/passwd" },
      },
      {
        name: "a value that is not a URL",
        env: { POSTHOG_CUSTOM_CLOUD_URL: "posthog.example.com" },
      },
    ])("returns null for $name", ({ env }) => {
      expect(readCustomCloudFromEnv(env)).toBeNull();
    });

    it("drops a gateway URL that is not http", () => {
      expect(
        readCustomCloudFromEnv({
          POSTHOG_CUSTOM_CLOUD_URL: "https://posthog.example.com",
          POSTHOG_CUSTOM_CLOUD_GATEWAY_URL: "ftp://gateway.example.com",
        })?.gatewayUrl,
      ).toBeUndefined();
    });
  });

  describe("configureCustomCloud", () => {
    it("makes the configured target the answer", () => {
      configureCustomCloud({ url: "https://posthog.example.com/" });
      expect(getCustomCloud()?.url).toBe("https://posthog.example.com");
      expect(hasCustomCloud()).toBe(true);
    });

    it("refuses a target that is not an http URL", () => {
      configureCustomCloud({ url: "not-a-url" });
      expect(hasCustomCloud()).toBe(false);
    });

    it("gives the environment back as the source when set to null", () => {
      configureCustomCloud({ url: "https://configured.example.com" });
      configureCustomCloud(null);
      vi.stubEnv("POSTHOG_CUSTOM_CLOUD_URL", "https://from-env.example.com");
      expect(getCustomCloud()?.url).toBe("https://from-env.example.com");
    });
  });
});

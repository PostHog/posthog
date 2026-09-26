import { afterEach, describe, expect, it, vi } from "vitest";
import {
  configureCustomCloud,
  getCustomCloud,
  isCustomCloudHost,
  normalizeCustomCloud,
  validateAiGatewayUrl,
} from "./custom-cloud";

describe("custom cloud", () => {
  afterEach(() => {
    configureCustomCloud(null);
    vi.unstubAllEnvs();
  });

  describe("normalizeCustomCloud", () => {
    it("trims the values and keeps the origin only", () => {
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

    it("accepts plain http on an IPv6 loopback", () => {
      expect(
        normalizeCustomCloud({
          url: "http://[::1]:8000",
          oauthClientId: "local",
        })?.url,
      ).toBe("http://[::1]:8000");
    });

    it.each([
      { name: "no input", url: undefined },
      { name: "an empty URL", url: "  " },
      { name: "a scheme that is not http", url: "file:///etc/passwd" },
      { name: "a value that is not a URL", url: "posthog.example.com" },
      { name: "a path", url: "https://posthog.example.com/project/1" },
      { name: "a query", url: "https://posthog.example.com/?a=1" },
      { name: "a fragment", url: "https://posthog.example.com/#settings" },
    ])("returns null for $name", ({ url }) => {
      expect(
        normalizeCustomCloud(url === undefined ? null : { url }),
      ).toBeNull();
    });

    it("returns null without an OAuth client ID", () => {
      expect(
        normalizeCustomCloud({ url: "https://posthog.example.com" }),
      ).toBeNull();
      expect(
        normalizeCustomCloud({
          url: "https://posthog.example.com",
          oauthClientId: "  ",
        }),
      ).toBeNull();
    });

    it("keeps an http URL only for a loopback host", () => {
      expect(
        normalizeCustomCloud({
          url: "http://localhost:8020",
          oauthClientId: "client-id",
        })?.url,
      ).toBe("http://localhost:8020");
      expect(
        normalizeCustomCloud({
          url: "http://posthog.example.com",
          oauthClientId: "client-id",
        }),
      ).toBeNull();
    });

    it("refuses a built-in host written with a trailing dot", () => {
      expect(
        normalizeCustomCloud({
          url: "https://us.posthog.com.",
          oauthClientId: "client-id",
        }),
      ).toBeNull();
    });

    it.each([
      "https://us.posthog.com",
      "https://eu.posthog.com",
      "https://app.dev.posthog.dev",
      "http://localhost:8010",
    ])("refuses the built-in host %s", (url) => {
      expect(normalizeCustomCloud({ url })).toBeNull();
    });

    it("drops a gateway URL that is not a plain origin", () => {
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
      configureCustomCloud({
        url: "https://configured.example.com",
        oauthClientId: "configured-client-id",
      });
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
    });
  });

  describe("isCustomCloudHost", () => {
    it("matches the configured host only", () => {
      configureCustomCloud({
        url: "https://posthog.example.com",
        oauthClientId: "client-id",
      });
      expect(isCustomCloudHost("https://posthog.example.com/")).toBe(true);
      expect(isCustomCloudHost("https://us.posthog.com")).toBe(false);
    });

    it("matches nothing when no target is configured", () => {
      vi.stubEnv("POSTHOG_CUSTOM_CLOUD_URL", "");
      expect(isCustomCloudHost("https://posthog.example.com")).toBe(false);
    });
  });
});

describe("validateAiGatewayUrl", () => {
  afterEach(() => configureCustomCloud(null));

  it.each([
    "https://ai-gateway.us.posthog.com",
    "https://ai-gateway.eu.posthog.com/",
    "https://ai-gateway.dev.posthog.dev",
    "https://AI-GATEWAY.US.POSTHOG.COM.",
  ])("accepts %s", (raw) => {
    expect(validateAiGatewayUrl(raw)).toBe(
      new URL(raw).origin.replace(/\.$/, ""),
    );
  });

  it.each([
    "http://ai-gateway.us.posthog.com",
    "https://evil.example",
    "https://evilposthog.com",
    "https://us.posthog.com",
    "https://llm.posthog.com",
    "https://attacker.github.io",
    "https://ai-gateway.us.posthog.com.evil.example",
    "https://x-ai-gateway.us.posthog.com.evil.example",
    "https://1.2.3.4",
    "https://ai-gateway.us.posthog.com/v1",
    "https://ai-gateway.us.posthog.com?x=1",
    "https://user:pw@ai-gateway.us.posthog.com",
    "http://localhost:3308",
    "https://127.0.0.1:3308",
    "not a url",
  ])("rejects %s", (raw) => {
    expect(validateAiGatewayUrl(raw)).toBeNull();
  });

  it("accepts loopback only under the dev override", () => {
    expect(
      validateAiGatewayUrl("http://localhost:3308", { allowLoopback: true }),
    ).toBe("http://localhost:3308");
    expect(
      validateAiGatewayUrl("http://[::1]:3308", { allowLoopback: true }),
    ).toBe("http://[::1]:3308");
    expect(validateAiGatewayUrl("http://[::1]:3308")).toBeNull();
    expect(
      validateAiGatewayUrl("https://gateway.example", { allowLoopback: true }),
    ).toBeNull();
  });

  it.each([
    ["https://us.posthog.com", "https://ai-gateway.dev.posthog.dev"],
    ["https://app.dev.posthog.dev", "https://ai-gateway.us.posthog.com"],
    ["http://localhost:8000", "https://ai-gateway.us.posthog.com"],
  ])("refuses a gateway outside the domain of %s", (apiHost, raw) => {
    expect(validateAiGatewayUrl(raw, { apiHost })).toBeNull();
  });

  it.each([
    ["https://us.posthog.com", "https://ai-gateway.us.posthog.com"],
    ["https://eu.posthog.com", "https://ai-gateway.eu.posthog.com"],
    ["https://app.dev.posthog.dev", "https://ai-gateway.dev.posthog.dev"],
  ])("accepts a gateway in the domain of %s", (apiHost, raw) => {
    expect(validateAiGatewayUrl(raw, { apiHost })).toBe(raw);
  });
});

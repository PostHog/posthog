import { afterEach, describe, expect, it, vi } from "vitest";
import {
  configureCustomCloud,
  getCustomCloud,
  isCredentialOriginAllowed,
  isCustomCloudHost,
  normalizeCustomCloud,
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

    it("accepts an http IPv6 loopback URL", () => {
      expect(
        normalizeCustomCloud({
          url: "http://[::1]:8000",
          oauthClientId: "client-id",
        })?.url,
      ).toBe("http://[::1]:8000");
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

describe("isCredentialOriginAllowed", () => {
  afterEach(() => configureCustomCloud(null));

  it.each([
    ["https://us.posthog.com/api/users/@me/", "https://us.posthog.com"],
    [
      "https://gateway.us.posthog.com/posthog_code/v1/messages",
      "https://us.posthog.com",
    ],
    ["https://mcp.posthog.com/mcp", "https://eu.posthog.com"],
    ["https://gateway.dev.posthog.dev/x", "https://app.dev.posthog.dev"],
    ["http://localhost:8787/mcp", "http://localhost:8010"],
    ["http://[::1]:8787/mcp", "http://localhost:8010"],
    ["http://localhost:8787/mcp", "http://[::1]:8010"],
    ["http://posthog.internal:8000/api/x", "http://posthog.internal:8000"],
  ])("allows %s for %s", (url, apiHost) => {
    expect(isCredentialOriginAllowed(url, apiHost)).toBe(true);
  });

  it.each([
    ["https://evil.example/steal", "https://us.posthog.com"],
    ["http://us.posthog.com/api", "https://us.posthog.com"],
    ["http://localhost:8787/mcp", "https://us.posthog.com"],
    ["https://posthog.com.evil.example/", "https://us.posthog.com"],
    ["https://evilposthog.com/", "https://us.posthog.com"],
    ["https://1.2.3.4/", "https://us.posthog.com"],
    ["https://evilexample.com/", "https://posthog.example.com"],
    ["https://other.example/", "https://posthog.example.com"],
    ["https://1.2.3.4/", "https://10.0.0.5"],
    ["https://evil/", "https://posthog"],
    ["https://attacker.github.io/", "https://customer.github.io"],
    ["https://mcp.example.com/mcp", "https://posthog.example.com"],
    ["https://llm.acme.co.uk/", "https://posthog.acme.co.uk"],
    ["https://us.posthog.com/api", "https://posthog.example.com"],
    ["https://mcp.posthog.com/mcp", "https://app.dev.posthog.dev"],
    ["https://gateway.dev.posthog.dev/x", "https://us.posthog.com"],
    ["http://[::1]:8787/mcp", "https://us.posthog.com"],
  ])("refuses %s for %s", (url, apiHost) => {
    expect(isCredentialOriginAllowed(url, apiHost)).toBe(false);
  });

  it("allows a root-relative path and refuses a protocol-relative one", () => {
    expect(
      isCredentialOriginAllowed("/api/users/@me/", "https://us.posthog.com"),
    ).toBe(true);
    expect(
      isCredentialOriginAllowed("//evil.example/x", "https://us.posthog.com"),
    ).toBe(false);
  });

  it.each(["/\\evil.example/x", "/\\/evil.example/x", "/\t/evil.example/x"])(
    "refuses %j, which the URL parser reads as protocol-relative",
    (url) => {
      expect(isCredentialOriginAllowed(url, "https://us.posthog.com")).toBe(
        false,
      );
    },
  );

  it("allows explicit extra origins and the custom cloud gateway", () => {
    expect(
      isCredentialOriginAllowed(
        "http://127.0.0.1:9000/mcp",
        "https://us.posthog.com",
        ["http://127.0.0.1:9000"],
      ),
    ).toBe(true);
    configureCustomCloud({
      url: "https://posthog.acme.internal",
      oauthClientId: "id",
      gatewayUrl: "https://llm.other-domain.io",
    });
    expect(
      isCredentialOriginAllowed(
        "https://llm.other-domain.io/posthog_code/v1/messages",
        "https://posthog.acme.internal",
      ),
    ).toBe(true);
  });
});

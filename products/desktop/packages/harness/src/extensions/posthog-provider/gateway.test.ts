import { configureCustomCloud } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  GATEWAY_PRODUCT,
  getGatewayBaseUrl,
  getLlmGatewayUrl,
  resolveExplicitRegion,
  resolveRegion,
} from "./gateway";

describe("getGatewayBaseUrl", () => {
  beforeEach(() => {
    // A custom cloud in the developer's own environment must not move the
    // default hosts.
    vi.stubEnv("POSTHOG_CUSTOM_CLOUD_URL", "");
    vi.stubEnv("VITE_POSTHOG_CUSTOM_CLOUD_URL", "");
    configureCustomCloud(null);
  });

  afterEach(() => {
    configureCustomCloud(null);
    vi.unstubAllEnvs();
  });

  it("sends the dev region to the gateway of a configured custom cloud", () => {
    configureCustomCloud({
      url: "https://posthog.example.com",
      gatewayUrl: "https://gateway.example.com",
    });
    expect(getGatewayBaseUrl("dev")).toBe("https://gateway.example.com");
    expect(getGatewayBaseUrl("us")).toBe("https://gateway.us.posthog.com");
  });

  it("keeps the local gateway when a custom cloud has no gateway", () => {
    configureCustomCloud({ url: "https://posthog.example.com" });
    expect(getGatewayBaseUrl("dev")).toBe("http://localhost:3308");
  });

  it("maps each region to its own gateway host", () => {
    expect(getGatewayBaseUrl("us")).toBe("https://gateway.us.posthog.com");
    expect(getGatewayBaseUrl("eu")).toBe("https://gateway.eu.posthog.com");
    expect(getGatewayBaseUrl("dev")).toBe("http://localhost:3308");
    expect(getGatewayBaseUrl("dev-cloud")).toBe(
      "https://gateway.dev.posthog.dev",
    );
  });
});

describe("getLlmGatewayUrl", () => {
  it("appends the product path to the region gateway host", () => {
    expect(getLlmGatewayUrl("us")).toBe(
      `https://gateway.us.posthog.com/${GATEWAY_PRODUCT}`,
    );
    expect(getLlmGatewayUrl("eu")).toBe(
      `https://gateway.eu.posthog.com/${GATEWAY_PRODUCT}`,
    );
    expect(getLlmGatewayUrl("dev")).toBe(
      `http://localhost:3308/${GATEWAY_PRODUCT}`,
    );
    expect(getLlmGatewayUrl("dev-cloud")).toBe(
      `https://gateway.dev.posthog.dev/${GATEWAY_PRODUCT}`,
    );
  });
});

describe("resolveRegion", () => {
  const originalRegion = process.env.POSTHOG_REGION;

  beforeEach(() => {
    delete process.env.POSTHOG_REGION;
  });

  afterEach(() => {
    if (originalRegion === undefined) {
      delete process.env.POSTHOG_REGION;
    } else {
      process.env.POSTHOG_REGION = originalRegion;
    }
  });

  it("prefers the explicit region over the environment", () => {
    process.env.POSTHOG_REGION = "eu";
    expect(resolveRegion("dev")).toBe("dev");
  });

  it("falls back to a valid POSTHOG_REGION environment variable", () => {
    process.env.POSTHOG_REGION = "eu";
    expect(resolveRegion()).toBe("eu");
  });

  it.each(["us", "eu", "dev", "dev-cloud"] as const)(
    "accepts %s from the environment",
    (region) => {
      process.env.POSTHOG_REGION = region;
      expect(resolveRegion()).toBe(region);
    },
  );

  it("defaults to us when nothing is set", () => {
    expect(resolveRegion()).toBe("us");
  });

  it("defaults to us when the environment value is not a known region", () => {
    process.env.POSTHOG_REGION = "not-a-region";
    expect(resolveRegion()).toBe("us");
  });

  it("defaults to us when explicit and environment are both unset", () => {
    expect(resolveRegion(undefined)).toBe("us");
  });
});

describe("resolveExplicitRegion", () => {
  const originalRegion = process.env.POSTHOG_REGION;

  beforeEach(() => {
    delete process.env.POSTHOG_REGION;
  });

  afterEach(() => {
    if (originalRegion === undefined) {
      delete process.env.POSTHOG_REGION;
    } else {
      process.env.POSTHOG_REGION = originalRegion;
    }
  });

  it("returns undefined when nothing was configured", () => {
    expect(resolveExplicitRegion()).toBeUndefined();
  });

  it("returns undefined when the environment value is not a known region", () => {
    process.env.POSTHOG_REGION = "not-a-region";
    expect(resolveExplicitRegion()).toBeUndefined();
  });

  it("returns the explicit option when given", () => {
    expect(resolveExplicitRegion("dev")).toBe("dev");
  });

  it("prefers the explicit option over the environment", () => {
    process.env.POSTHOG_REGION = "eu";
    expect(resolveExplicitRegion("dev")).toBe("dev");
  });

  it("falls back to a valid POSTHOG_REGION when no explicit option is given", () => {
    process.env.POSTHOG_REGION = "dev";
    expect(resolveExplicitRegion()).toBe("dev");
  });
});

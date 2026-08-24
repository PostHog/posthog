import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  GATEWAY_PRODUCT,
  getGatewayBaseUrl,
  getLlmGatewayUrl,
  resolveExplicitRegion,
  resolveRegion,
} from "./gateway";

describe("getGatewayBaseUrl", () => {
  it("maps each region to its own gateway host", () => {
    expect(getGatewayBaseUrl("us")).toBe("https://gateway.us.posthog.com");
    expect(getGatewayBaseUrl("eu")).toBe("https://gateway.eu.posthog.com");
    expect(getGatewayBaseUrl("dev")).toBe("http://localhost:3308");
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

  it.each(["us", "eu", "dev"] as const)(
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

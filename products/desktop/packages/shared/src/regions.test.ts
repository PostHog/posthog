import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configureCustomCloud } from "./custom-cloud";
import {
  getOauthClientIdFromRegion,
  POSTHOG_DEV_CLIENT_ID,
  POSTHOG_DEV_CLOUD_CLIENT_ID,
  POSTHOG_EU_CLIENT_ID,
  POSTHOG_US_CLIENT_ID,
} from "./oauth";
import {
  CLOUD_REGIONS,
  describeRegion,
  formatRegionBadge,
  REGION_LABELS,
} from "./regions";
import { getCloudUrlFromRegion } from "./urls";

beforeEach(() => {
  // A custom cloud in the developer's own environment must not move the
  // default targets that the tests below assert.
  vi.stubEnv("POSTHOG_CUSTOM_CLOUD_URL", "");
  vi.stubEnv("VITE_POSTHOG_CUSTOM_CLOUD_URL", "");
  configureCustomCloud(null);
});

afterEach(() => {
  configureCustomCloud(null);
  vi.unstubAllEnvs();
});

describe("getCloudUrlFromRegion", () => {
  it("maps each region to its cloud URL", () => {
    expect(getCloudUrlFromRegion("us")).toBe("https://us.posthog.com");
    expect(getCloudUrlFromRegion("eu")).toBe("https://eu.posthog.com");
    expect(getCloudUrlFromRegion("dev")).toBe("http://localhost:8010");
    expect(getCloudUrlFromRegion("dev-cloud")).toBe(
      "https://app.dev.posthog.dev",
    );
  });
});

describe("getOauthClientIdFromRegion", () => {
  it("maps each region to its distinct OAuth client id", () => {
    expect(getOauthClientIdFromRegion("us")).toBe(POSTHOG_US_CLIENT_ID);
    expect(getOauthClientIdFromRegion("eu")).toBe(POSTHOG_EU_CLIENT_ID);
    expect(getOauthClientIdFromRegion("dev")).toBe(POSTHOG_DEV_CLIENT_ID);
    expect(getOauthClientIdFromRegion("dev-cloud")).toBe(
      POSTHOG_DEV_CLOUD_CLIENT_ID,
    );
  });

  it("uses a different client id per region", () => {
    const ids = new Set([
      getOauthClientIdFromRegion("us"),
      getOauthClientIdFromRegion("eu"),
      getOauthClientIdFromRegion("dev"),
      getOauthClientIdFromRegion("dev-cloud"),
    ]);
    expect(ids.size).toBe(CLOUD_REGIONS.length);
  });
});

describe("a configured custom cloud", () => {
  beforeEach(() => {
    configureCustomCloud({
      url: "https://posthog.example.com/",
      oauthClientId: "custom-client-id",
    });
  });

  it("moves the dev region only", () => {
    expect(getCloudUrlFromRegion("dev")).toBe("https://posthog.example.com");
    expect(getOauthClientIdFromRegion("dev")).toBe("custom-client-id");
    expect(getCloudUrlFromRegion("us")).toBe("https://us.posthog.com");
    expect(getCloudUrlFromRegion("eu")).toBe("https://eu.posthog.com");
    expect(getCloudUrlFromRegion("dev-cloud")).toBe(
      "https://app.dev.posthog.dev",
    );
    expect(getOauthClientIdFromRegion("us")).toBe(POSTHOG_US_CLIENT_ID);
  });

  it("labels the dev region with the custom host", () => {
    expect(describeRegion("dev")).toMatchObject({
      label: "Custom cloud",
      hint: "posthog.example.com",
    });
    expect(describeRegion("us")).toEqual(REGION_LABELS.us);
  });
});

describe("formatRegionBadge", () => {
  it("labels the two development targets with their hosts", () => {
    expect(REGION_LABELS.dev).toMatchObject({
      label: "Local development",
      hint: "localhost:8010",
    });
    expect(REGION_LABELS["dev-cloud"]).toMatchObject({
      label: "Dev Cloud",
      hint: "app.dev.posthog.dev",
    });
  });

  it("combines the flag and label for a region", () => {
    expect(formatRegionBadge("us")).toBe(
      `${REGION_LABELS.us.flag} ${REGION_LABELS.us.label}`,
    );
  });

  it("formats every known region without throwing", () => {
    for (const region of CLOUD_REGIONS) {
      expect(formatRegionBadge(region)).toContain(REGION_LABELS[region].label);
    }
  });
});

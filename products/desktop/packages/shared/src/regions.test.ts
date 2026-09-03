import { describe, expect, it } from "vitest";
import {
  getOauthClientIdFromRegion,
  POSTHOG_DEV_CLIENT_ID,
  POSTHOG_DEV_CLOUD_CLIENT_ID,
  POSTHOG_EU_CLIENT_ID,
  POSTHOG_US_CLIENT_ID,
} from "./oauth";
import { CLOUD_REGIONS, formatRegionBadge, REGION_LABELS } from "./regions";
import { getCloudUrlFromRegion } from "./urls";

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

import { describe, expect, it } from "vitest";
import { cloudRegion } from "./oauth.schemas";

describe("cloudRegion", () => {
  it.each(["dev", "dev-cloud"] as const)(
    "accepts a serialized %s region",
    (region) => {
      const serialized = JSON.stringify(region);
      expect(cloudRegion.parse(JSON.parse(serialized))).toBe(region);
    },
  );
});

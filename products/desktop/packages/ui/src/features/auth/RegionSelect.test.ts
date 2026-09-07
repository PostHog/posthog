import { describe, expect, it } from "vitest";
import { getSelectableRegions } from "./RegionSelect";

describe("getSelectableRegions", () => {
  it.each([
    { includeDevRegion: false, includePreview: false, expected: ["us", "eu"] },
    {
      includeDevRegion: true,
      includePreview: false,
      expected: ["us", "eu", "dev-cloud", "dev"],
    },
    {
      includeDevRegion: false,
      includePreview: true,
      expected: ["preview", "us", "eu"],
    },
  ])(
    "offers development regions $includeDevRegion and the preview $includePreview",
    ({ includeDevRegion, includePreview, expected }) => {
      expect(getSelectableRegions(includeDevRegion, includePreview)).toEqual(
        expected,
      );
    },
  );
});

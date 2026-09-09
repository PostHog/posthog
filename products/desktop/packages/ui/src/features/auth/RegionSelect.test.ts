import { describe, expect, it } from "vitest";
import { getSelectableRegions } from "./RegionSelect";

describe("getSelectableRegions", () => {
  it.each([
    {
      includeDevRegion: false,
      includeCustomRegion: false,
      expected: ["us", "eu"],
    },
    {
      includeDevRegion: true,
      includeCustomRegion: false,
      expected: ["us", "eu", "dev-cloud", "dev"],
    },
    {
      includeDevRegion: true,
      includeCustomRegion: true,
      expected: ["us", "eu", "dev-cloud", "dev", "custom"],
    },
    {
      includeDevRegion: false,
      includeCustomRegion: true,
      expected: ["us", "eu", "custom"],
    },
  ])(
    "offers development $includeDevRegion and custom $includeCustomRegion",
    ({ includeDevRegion, includeCustomRegion, expected }) => {
      expect(
        getSelectableRegions(includeDevRegion, includeCustomRegion),
      ).toEqual(expected);
    },
  );
});

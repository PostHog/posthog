import { describe, expect, it } from "vitest";
import { getSelectableRegions } from "./RegionSelect";

describe("getSelectableRegions", () => {
  it.each([
    { includeDevRegion: false, expected: ["us", "eu"] },
    {
      includeDevRegion: true,
      expected: ["us", "eu", "dev-cloud", "dev", "custom"],
    },
  ])(
    "returns the regions available when development regions are $includeDevRegion",
    ({ includeDevRegion, expected }) => {
      expect(getSelectableRegions(includeDevRegion)).toEqual(expected);
    },
  );
});

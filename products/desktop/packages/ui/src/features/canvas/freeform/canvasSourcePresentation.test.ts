import { describe, expect, it } from "vitest";
import {
  hasCanvasSource,
  shouldLoadCanvasHeadSource,
} from "./canvasSourcePresentation";

describe("canvas source presentation", () => {
  it.each([
    {
      name: "an unbuilt canvas after its record and lifecycle load",
      input: {
        dashboardLoaded: true,
        lifecycleLoaded: true,
        hasPublishedBuild: false,
      },
      expected: true,
    },
    {
      name: "a canvas whose published build is renderable",
      input: {
        dashboardLoaded: true,
        lifecycleLoaded: true,
        hasPublishedBuild: true,
      },
      expected: false,
    },
    {
      name: "a canvas whose record is still loading",
      input: {
        dashboardLoaded: false,
        lifecycleLoaded: true,
        hasPublishedBuild: false,
      },
      expected: false,
    },
    {
      name: "a canvas whose lifecycle is still loading",
      input: {
        dashboardLoaded: true,
        lifecycleLoaded: false,
        hasPublishedBuild: false,
      },
      expected: false,
    },
  ])("loads head source for $name", ({ input, expected }) => {
    expect(shouldLoadCanvasHeadSource(input)).toBe(expected);
  });

  it.each([
    {
      name: "a relational source version",
      input: { headVersionId: "version-1", headCode: undefined },
      expected: true,
    },
    {
      name: "migrated legacy code",
      input: {
        headVersionId: null,
        headCode: "export default function Canvas() { return null }",
      },
      expected: true,
    },
    {
      name: "an empty synthetic project",
      input: { headVersionId: null, headCode: "" },
      expected: false,
    },
  ])("detects source for $name", ({ input, expected }) => {
    expect(hasCanvasSource(input)).toBe(expected);
  });
});

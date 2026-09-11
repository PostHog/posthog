import type { CanvasBuildRecord } from "@posthog/core/canvas/canvasBuildSchemas";
import { describe, expect, it } from "vitest";
import {
  canvasArtifactBase,
  formatPendingFragments,
  fragmentProgress,
  fragmentsForBuild,
  shouldRollForwardFragments,
} from "./canvasFragments";

const manifest = {
  entryHtml: "index.html",
  assets: [],
  dependencies: {},
  canvasSdkVersion: "0.2.0",
  capabilities: {
    posthog: {
      insights: [],
      inlineQueries: false,
      captureEvents: [],
      state: [],
      actions: [],
      agentRequests: false,
    },
    network: { origins: [] },
    connectors: [],
  },
};

describe("canvasFragments", () => {
  it.each([
    {
      name: "the flag is off",
      mounted: { id: "b1", layoutHash: "L" },
      latest: { id: "b2", layoutHash: "L" },
      flagOn: false,
      expected: false,
    },
    {
      name: "nothing is mounted",
      mounted: null,
      latest: { id: "b2", layoutHash: "L" },
      flagOn: true,
      expected: false,
    },
    {
      name: "no newer build exists",
      mounted: { id: "b1", layoutHash: "L" },
      latest: null,
      flagOn: true,
      expected: false,
    },
    {
      name: "the latest build is the mounted one",
      mounted: { id: "b1", layoutHash: "L" },
      latest: { id: "b1", layoutHash: "L" },
      flagOn: true,
      expected: false,
    },
    {
      name: "the mounted build has no layoutHash",
      mounted: { id: "b1", layoutHash: undefined },
      latest: { id: "b2", layoutHash: "L" },
      flagOn: true,
      expected: false,
    },
    {
      name: "the latest build has no layoutHash",
      mounted: { id: "b1", layoutHash: "L" },
      latest: { id: "b2", layoutHash: undefined },
      flagOn: true,
      expected: false,
    },
    {
      name: "the layout changed",
      mounted: { id: "b1", layoutHash: "L" },
      latest: { id: "b2", layoutHash: "M" },
      flagOn: true,
      expected: false,
    },
    {
      name: "a newer build shares the layout",
      mounted: { id: "b1", layoutHash: "L" },
      latest: { id: "b2", layoutHash: "L" },
      flagOn: true,
      expected: true,
    },
  ])(
    "shouldRollForwardFragments is $expected when $name",
    ({ mounted, latest, flagOn, expected }) => {
      expect(shouldRollForwardFragments(mounted, latest, flagOn)).toBe(
        expected,
      );
    },
  );

  it.each([
    [
      "https://usercontent.example/canvas-artifacts/tok/index.html?sig=1#x",
      "index.html",
      "https://usercontent.example/canvas-artifacts/tok/",
    ],
    [
      "https://usercontent.example/canvas-artifacts/tok/dist/index.html",
      "dist/index.html",
      "https://usercontent.example/canvas-artifacts/tok/",
    ],
    [
      "https://usercontent.example/canvas-artifacts/tok/other.html",
      "index.html",
      "https://usercontent.example/canvas-artifacts/tok/",
    ],
  ])("canvasArtifactBase(%s, %s) is %s", (url, entry, expected) => {
    expect(canvasArtifactBase(url, entry)).toBe(expected);
  });

  it("builds the set-fragments payload with an absolute platform stylesheet", () => {
    const build = {
      id: "b2",
      artifactUrl:
        "https://usercontent.example/canvas-artifacts/tok/index.html",
      manifest: {
        ...manifest,
        fragments: {
          "src/fragments/revenue.tsx": {
            file: "fragments/revenue.abc.js",
            contentHash: "abc",
          },
        },
        layoutHash: "L",
        platformCss: "platform.css",
      },
    } as unknown as CanvasBuildRecord;

    expect(fragmentsForBuild(build)).toEqual({
      base: "https://usercontent.example/canvas-artifacts/tok/",
      fragments: build.manifest?.fragments,
      platformCss:
        "https://usercontent.example/canvas-artifacts/tok/platform.css",
    });
  });

  it.each<
    [
      string,
      {
        artifactUrl: string | null;
        layoutHash?: string;
        fragments?: Record<string, { file: string; contentHash: string }>;
      },
    ]
  >([
    ["no artifact URL", { artifactUrl: null, layoutHash: "L", fragments: {} }],
    ["no layoutHash", { artifactUrl: "https://u.example/t/index.html" }],
  ])("has no fragments payload for a build with %s", (_name, overrides) => {
    const build = {
      id: "b",
      artifactUrl: overrides.artifactUrl,
      manifest: {
        ...manifest,
        fragments: overrides.fragments,
        layoutHash: overrides.layoutHash,
      },
    } as unknown as CanvasBuildRecord;

    expect(fragmentsForBuild(build)).toBeUndefined();
  });

  it.each([
    ["no manifest", undefined, null],
    ["no markers", manifest, null],
    [
      "every marker ready",
      { ...manifest, markers: ["a", "b"] },
      {
        ready: 2,
        total: 2,
        pending: [],
      },
    ],
    [
      "one marker pending",
      { ...manifest, markers: ["a", "b"], pendingFragments: ["b"] },
      { ready: 1, total: 2, pending: ["b"] },
    ],
  ])("fragmentProgress reports %s", (_name, input, expected) => {
    expect(fragmentProgress(input)).toEqual(expected);
  });

  it.each([
    [
      ["a", "b"],
      ["a", "b"],
    ],
    [
      ["a", "b", "c", "d", "e", "f", "g"],
      ["a", "b", "c", "d", "e", "+2 more"],
    ],
  ])("formatPendingFragments truncates %j", (pending, expected) => {
    expect(formatPendingFragments(pending)).toEqual(expected);
  });
});

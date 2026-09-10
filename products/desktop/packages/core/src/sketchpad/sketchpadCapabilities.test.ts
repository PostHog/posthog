import type {
  SketchpadCapabilities,
  SketchpadDataMethod,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { assertSketchpadCapability } from "./sketchpadCapabilities";

describe("assertSketchpadCapability", () => {
  const declared: SketchpadCapabilities = {
    inlineQueries: true,
    insights: ["abc123"],
    state: ["shared"],
  };
  const nothing: SketchpadCapabilities = {
    inlineQueries: false,
    insights: [],
    state: [],
  };

  it.each<
    [string, SketchpadCapabilities | undefined, SketchpadDataMethod, unknown]
  >([
    ["undeclared query", nothing, "query", { hogql: "select 1" }],
    ["undeclared insight", nothing, "loadInsight", { shortId: "abc123" }],
    ["another canvas's insight", declared, "loadInsight", { shortId: "other" }],
    ["undeclared state read", nothing, "stateGet", { key: "note" }],
    ["undeclared state write", nothing, "stateSet", { key: "note", value: 1 }],
    ["no manifest at all", undefined, "query", { hogql: "select 1" }],
  ])("refuses %s", (_name, capabilities, method, payload) => {
    expect(() =>
      assertSketchpadCapability(capabilities, method, payload),
    ).toThrow();
  });

  it.each<
    [string, SketchpadCapabilities | undefined, SketchpadDataMethod, unknown]
  >([
    ["a declared query", declared, "query", { hogql: "select 1" }],
    ["a declared insight", declared, "loadInsight", { shortId: "abc123" }],
    ["a declared state write", declared, "stateSet", { key: "note", value: 1 }],
    ["layout without a manifest", undefined, "arrangeFragments", { items: [] }],
  ])("allows %s", (_name, capabilities, method, payload) => {
    expect(() =>
      assertSketchpadCapability(capabilities, method, payload),
    ).not.toThrow();
  });
});

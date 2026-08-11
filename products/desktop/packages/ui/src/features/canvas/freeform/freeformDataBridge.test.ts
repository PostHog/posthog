import { assertCanvasCapability } from "@posthog/core/canvas/canvasCapabilities";
import type { CanvasCapabilities } from "@posthog/shared";
import { describe, expect, it } from "vitest";

const capabilities: CanvasCapabilities = {
  posthog: {
    insights: ["allowed-insight"],
    inlineQueries: false,
    captureEvents: ["allowed-event"],
  },
  network: { origins: [] },
};

describe("assertCanvasCapability", () => {
  it.each([
    ["query", { hogql: "select 1" }],
    ["loadInsight", { shortId: "other-insight" }],
    ["capture", { event: "other-event" }],
  ])("rejects undeclared %s access", (method, payload) => {
    expect(() => assertCanvasCapability(capabilities, method, payload)).toThrow(
      "not allowed",
    );
  });

  it.each([
    ["loadInsight", { shortId: "allowed-insight" }],
    ["capture", { event: "allowed-event" }],
  ])("allows declared %s access", (method, payload) => {
    expect(() =>
      assertCanvasCapability(capabilities, method, payload),
    ).not.toThrow();
  });

  it("rejects requests when the published manifest is missing", () => {
    expect(() =>
      assertCanvasCapability(undefined, "query", { hogql: "select 1" }),
    ).toThrow("manifest");
  });

  it("rejects methods that are not covered by the manifest", () => {
    expect(() =>
      assertCanvasCapability(capabilities, "run", { query: "select 1" }),
    ).toThrow('Method "run" is not allowed');
  });
});

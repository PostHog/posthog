import { assertCanvasCapability } from "@posthog/core/canvas/canvasCapabilities";
import type { CanvasCapabilities } from "@posthog/shared";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { handleFreeformDataRequest } from "./freeformDataBridge";

const loadInsight = vi.fn();
vi.mock("../hostClient", () => ({
  hostClient: () => ({ canvasData: { loadInsight: { mutate: loadInsight } } }),
}));

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

describe("handleFreeformDataRequest", () => {
  // Reads are cached by their content, so `variables` has to be part of the key. If
  // it isn't, one insight rendered per product resolves every product from the first
  // product's cache entry — a whole board of identical numbers, no error anywhere.
  it("does not share a cached insight read across different SQL variables", async () => {
    const queryClient = new QueryClient();
    loadInsight.mockReset();
    loadInsight
      .mockResolvedValueOnce({ columns: ["mrr"], results: [[1]] })
      .mockResolvedValueOnce({ columns: ["mrr"], results: [[2]] });

    const read = (product: string) =>
      handleFreeformDataRequest(
        "loadInsight",
        { shortId: "abc123", variables: { product } },
        queryClient,
      );

    expect(await read("surveys")).toEqual({ columns: ["mrr"], results: [[1]] });
    expect(await read("session_replay")).toEqual({
      columns: ["mrr"],
      results: [[2]],
    });
    expect(loadInsight).toHaveBeenCalledTimes(2);

    // Same variables again still resolves from cache rather than re-querying.
    expect(await read("surveys")).toEqual({ columns: ["mrr"], results: [[1]] });
    expect(loadInsight).toHaveBeenCalledTimes(2);
  });
});

import { assertCanvasCapability } from "@posthog/core/canvas/canvasCapabilities";
import type { CanvasCapabilities } from "@posthog/shared";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { handleFreeformDataRequest } from "./freeformDataBridge";

const loadInsight = vi.fn();
const setState = vi.fn();
const listState = vi.fn();
const invokeAction = vi.fn();
vi.mock("../hostClient", () => ({
  hostClient: () => ({
    canvasData: { loadInsight: { mutate: loadInsight } },
    dashboards: {
      setState: { mutate: setState },
      listState: { query: listState },
      invokeAction: { mutate: invokeAction },
    },
  }),
}));

const capabilities: CanvasCapabilities = {
  posthog: {
    insights: ["allowed-insight"],
    inlineQueries: false,
    agentRequests: false,
    captureEvents: ["allowed-event"],
    state: ["user"],
    actions: ["tasks.create"],
  },
  network: { origins: [] },
};

describe("assertCanvasCapability", () => {
  it.each([
    ["query", { hogql: "select 1" }],
    ["loadInsight", { shortId: "other-insight" }],
    ["capture", { event: "other-event" }],
    ["stateSet", { scope: "shared", key: "k", value: 1 }],
    ["actionInvoke", { verb: "annotations.create", payload: {} }],
    ["agentRequest", { prompt: "Change it" }],
  ])("rejects undeclared %s access", (method, payload) => {
    expect(() => assertCanvasCapability(capabilities, method, payload)).toThrow(
      "not allowed",
    );
  });

  it.each([
    ["loadInsight", { shortId: "allowed-insight" }],
    ["capture", { event: "allowed-event" }],
    ["stateGet", { scope: "user", key: "k" }],
    ["actionInvoke", { verb: "tasks.create", payload: {} }],
  ])("allows declared %s access", (method, payload) => {
    expect(() =>
      assertCanvasCapability(capabilities, method, payload),
    ).not.toThrow();
  });

  it("allows agent requests only when the manifest declares them", () => {
    expect(() =>
      assertCanvasCapability(
        {
          ...capabilities,
          posthog: { ...capabilities.posthog, agentRequests: true },
        },
        "agentRequest",
        { prompt: "Change it" },
      ),
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
  // State and actions are canvas-scoped writes: routing them without the canvas
  // identity would write one canvas's state under another's keys.
  it("routes state writes to the canvas passed in context", async () => {
    const queryClient = new QueryClient();
    setState.mockReset().mockResolvedValue(undefined);

    await handleFreeformDataRequest(
      "stateSet",
      { key: "k", value: 1, scope: "user" },
      queryClient,
      { dashboardId: "canvas-1" },
    );

    expect(setState).toHaveBeenCalledWith({
      id: "canvas-1",
      scope: "user",
      key: "k",
      value: 1,
    });
  });

  it.each([
    ["stateSet", { key: "k", value: 1 }],
    ["stateList", {}],
    ["actionInvoke", { verb: "tasks.create", payload: {} }],
  ])("%s without a canvas context is refused", async (method, payload) => {
    const queryClient = new QueryClient();

    await expect(
      handleFreeformDataRequest(method, payload, queryClient),
    ).rejects.toThrow("requires a canvas context");
  });

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

  it("refreshes a cached read after its declared interval", async () => {
    vi.useFakeTimers();
    const queryClient = new QueryClient();
    loadInsight.mockReset();
    loadInsight
      .mockResolvedValueOnce({ columns: ["value"], results: [[1]] })
      .mockResolvedValueOnce({ columns: ["value"], results: [[2]] });

    const read = () =>
      handleFreeformDataRequest(
        "loadInsight",
        { shortId: "abc123", refresh: 30 },
        queryClient,
      );

    expect(await read()).toEqual({ columns: ["value"], results: [[1]] });
    await vi.advanceTimersByTimeAsync(30_001);
    expect(await read()).toEqual({ columns: ["value"], results: [[2]] });
    expect(loadInsight).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("rejects refresh intervals below the platform floor", async () => {
    await expect(
      handleFreeformDataRequest(
        "loadInsight",
        { shortId: "abc123", refresh: 29 },
        new QueryClient(),
      ),
    ).rejects.toThrow("between 30 and 86400 seconds");
  });
});

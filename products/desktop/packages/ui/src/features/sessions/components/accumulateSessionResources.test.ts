import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  accumulateSessionResources,
  createSessionResourcesTracker,
} from "./accumulateSessionResources";

function resourcesUsedMsg(
  ts: number,
  products: { id: string; label: string }[],
): AcpMessage {
  return {
    type: "acp_message",
    ts,
    message: {
      jsonrpc: "2.0",
      method: "_posthog/resources_used",
      params: { sessionId: "session-1", products },
    },
  };
}

describe("accumulateSessionResources", () => {
  it("collects products across notifications in first-seen order", () => {
    const events: AcpMessage[] = [
      resourcesUsedMsg(1, [{ id: "feature_flags", label: "Feature flags" }]),
      resourcesUsedMsg(2, [
        { id: "product_analytics", label: "Product analytics" },
      ]),
    ];

    expect(accumulateSessionResources(events)).toEqual([
      { id: "feature_flags", label: "Feature flags" },
      { id: "product_analytics", label: "Product analytics" },
    ]);
  });

  it("de-duplicates a product used across multiple turns", () => {
    const events: AcpMessage[] = [
      resourcesUsedMsg(1, [{ id: "feature_flags", label: "Feature flags" }]),
      resourcesUsedMsg(2, [{ id: "experiments", label: "Experiments" }]),
      // feature_flags used again on a later turn — must not appear twice.
      resourcesUsedMsg(3, [{ id: "feature_flags", label: "Feature flags" }]),
    ];

    const result = accumulateSessionResources(events);
    expect(result).toEqual([
      { id: "feature_flags", label: "Feature flags" },
      { id: "experiments", label: "Experiments" },
    ]);
  });

  it("ignores unrelated events and empty payloads", () => {
    const events: AcpMessage[] = [
      {
        type: "acp_message",
        ts: 1,
        message: {
          jsonrpc: "2.0",
          method: "_posthog/turn_complete",
          params: { stopReason: "end_turn" },
        },
      },
      resourcesUsedMsg(2, []),
    ];

    expect(accumulateSessionResources(events)).toEqual([]);
  });

  it("tracker only processes newly appended events", () => {
    const first = resourcesUsedMsg(1, [
      { id: "feature_flags", label: "Feature flags" },
    ]);
    const tracker = createSessionResourcesTracker();

    expect(tracker.update([first])).toEqual([
      { id: "feature_flags", label: "Feature flags" },
    ]);

    Object.defineProperty(first, "message", {
      get() {
        throw new Error("old event was read again");
      },
    });

    expect(
      tracker.update([
        first,
        resourcesUsedMsg(2, [
          { id: "product_analytics", label: "Product analytics" },
        ]),
      ]),
    ).toEqual([
      { id: "feature_flags", label: "Feature flags" },
      { id: "product_analytics", label: "Product analytics" },
    ]);
  });

  it("rebuilds without carrying over products when the list is replaced", () => {
    const tracker = createSessionResourcesTracker();

    tracker.update([
      resourcesUsedMsg(1, [{ id: "feature_flags", label: "Feature flags" }]),
      resourcesUsedMsg(2, [{ id: "experiments", label: "Experiments" }]),
    ]);

    // A shorter, unrelated list breaks the append invariant — the prior
    // products must not leak into the result.
    expect(
      tracker.update([
        resourcesUsedMsg(3, [
          { id: "product_analytics", label: "Product analytics" },
        ]),
      ]),
    ).toEqual([{ id: "product_analytics", label: "Product analytics" }]);
  });
});

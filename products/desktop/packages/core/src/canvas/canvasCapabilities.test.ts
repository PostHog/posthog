import { assertCanvasCapability } from "@posthog/core/canvas/canvasCapabilities";
import type { CanvasCapabilities } from "@posthog/shared";
import { describe, expect, it } from "vitest";

function capabilities(
  posthog: Partial<CanvasCapabilities["posthog"]>,
): CanvasCapabilities {
  return {
    posthog: {
      insights: [],
      inlineQueries: false,
      captureEvents: [],
      state: [],
      actions: [],
      agentRequests: false,
      activityFeed: false,
      ...posthog,
    },
    network: { origins: [] },
    connectors: [],
  };
}

describe("assertCanvasCapability", () => {
  it("refuses a task-activity read the build did not declare", () => {
    expect(() =>
      assertCanvasCapability(capabilities({}), "activityFeed", {}),
    ).toThrow(/not allowed/);
  });

  it("admits a task-activity read the build declared", () => {
    expect(() =>
      assertCanvasCapability(
        capabilities({ activityFeed: true }),
        "activityFeed",
        {},
      ),
    ).not.toThrow();
  });
});

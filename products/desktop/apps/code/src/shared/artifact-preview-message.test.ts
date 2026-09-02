import { describe, expect, it } from "vitest";
import { sanitizeArtifactBridgeMessage } from "./artifact-preview-message";

const marker = "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__";

function selectionMessage(): Record<string, unknown> {
  return {
    marker,
    channel: "artifact-comments-1",
    type: "selection",
    anchor: {
      kind: "text",
      quote: "Report",
      prefix: "",
      suffix: " total",
      start: 0,
      end: 6,
    },
    rect: { top: 1, left: 2, right: 3, bottom: 4, width: 1, height: 3 },
    triggerRect: {
      top: 5,
      left: 6,
      right: 7,
      bottom: 8,
      width: 1,
      height: 3,
    },
  };
}

describe("sanitizeArtifactBridgeMessage", () => {
  it("copies only bounded selection fields to guest IPC", () => {
    const value = selectionMessage();
    value.untrustedPayload = "x".repeat(1_000_000);

    const sanitized = sanitizeArtifactBridgeMessage(value);

    expect(sanitized).toEqual(selectionMessage());
    expect(sanitized).not.toHaveProperty("untrustedPayload");
  });

  it("accepts bounded selection position updates", () => {
    const rect = selectionMessage().rect;
    const message = {
      marker,
      channel: "artifact-comments-1",
      type: "selection-position",
      rect,
    };

    expect(sanitizeArtifactBridgeMessage(message)).toEqual(message);
  });

  it.each([
    ["an oversized quote", { anchor: { quote: "x".repeat(10_001) } }],
    [
      "too many resolutions",
      {
        type: "resolutions",
        items: Array.from({ length: 501 }, (_, index) => ({
          id: `comment-${index}`,
          status: "exact",
        })),
      },
    ],
    [
      "an invalid selection position",
      { type: "selection-position", rect: { top: Number.POSITIVE_INFINITY } },
    ],
    ["an unsupported message", { type: "open-external" }],
  ])("rejects %s", (_name, override) => {
    const value = selectionMessage();
    Object.assign(value, override);
    if ("anchor" in override) {
      value.anchor = {
        ...(selectionMessage().anchor as Record<string, unknown>),
        ...override.anchor,
      };
    }

    expect(sanitizeArtifactBridgeMessage(value)).toBeNull();
  });
});

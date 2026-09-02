import { posthogToolMeta } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { isUploadArtifactCall } from "./inlineArtifacts";
import { isShowActionsCall, readShowActions } from "./showActions";

function localToolMeta(tool: string) {
  return posthogToolMeta({
    toolName: `mcp__posthog-code-tools__${tool}`,
    mcp: { server: "posthog-code-tools", tool },
  });
}

describe("isShowActionsCall", () => {
  // Both tools ride the same local server, and both draw a card instead of a
  // tool row, so telling them apart is what keeps each card on its own call.
  it("tells show_actions apart from its sibling local tools", () => {
    expect(isShowActionsCall(localToolMeta("show_actions"))).toBe(true);
    expect(isShowActionsCall(localToolMeta("upload_artifact"))).toBe(false);
    expect(isUploadArtifactCall(localToolMeta("show_actions"))).toBe(false);
  });

  it("ignores a show_actions tool from a different MCP server", () => {
    const foreign = posthogToolMeta({
      toolName: "mcp__another-server__show_actions",
      mcp: { server: "another-server", tool: "show_actions" },
    });
    expect(isShowActionsCall(foreign)).toBe(false);
  });
});

describe("readShowActions", () => {
  it("drops an action the host would refuse to open", () => {
    const buttons = readShowActions({
      actions: [
        { kind: "compose", label: "Add PostHog", prompt: "/instrument" },
        { kind: "open_space", label: "Open the space", channel_id: "  " },
        { kind: "open_website", label: "Go", url: "https://evil.example" },
      ],
    });

    expect(buttons).toEqual([
      {
        label: "Add PostHog",
        action: { kind: "compose", prompt: "/instrument" },
      },
    ]);
  });

  it.each([undefined, null, {}, { actions: "nope" }])(
    "returns nothing for %s",
    (rawInput) => {
      expect(readShowActions(rawInput)).toEqual([]);
    },
  );
});

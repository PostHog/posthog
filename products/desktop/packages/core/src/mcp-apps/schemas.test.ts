import { describe, expect, it } from "vitest";
import {
  LEGACY_RESOURCE_URI_META_KEY,
  mcpAppActionSchema,
  POSTHOG_EXEC_TOOL_KEY,
  resolveResultResourceUri,
} from "./schemas";

describe("resolveResultResourceUri", () => {
  it("reads the modern nested _meta.ui.resourceUri", () => {
    expect(
      resolveResultResourceUri({ _meta: { ui: { resourceUri: "ui://x" } } }),
    ).toBe("ui://x");
  });

  it("falls back to the legacy flat key", () => {
    expect(
      resolveResultResourceUri({
        _meta: { [LEGACY_RESOURCE_URI_META_KEY]: "ui://y" },
      }),
    ).toBe("ui://y");
  });

  it("prefers the modern key over the legacy one", () => {
    expect(
      resolveResultResourceUri({
        _meta: {
          ui: { resourceUri: "ui://modern" },
          [LEGACY_RESOURCE_URI_META_KEY]: "ui://legacy",
        },
      }),
    ).toBe("ui://modern");
  });

  it("returns undefined when there is no UI resource", () => {
    expect(resolveResultResourceUri({ content: [] })).toBeUndefined();
    expect(resolveResultResourceUri({ _meta: {} })).toBeUndefined();
    expect(
      resolveResultResourceUri({ _meta: { ui: { resourceUri: "" } } }),
    ).toBeUndefined();
    expect(resolveResultResourceUri("a string result")).toBeUndefined();
    expect(resolveResultResourceUri(null)).toBeUndefined();
    expect(resolveResultResourceUri(undefined)).toBeUndefined();
  });

  it("pins the built-in exec tool key", () => {
    expect(POSTHOG_EXEC_TOOL_KEY).toBe("mcp__posthog__exec");
  });
});

describe("mcpAppActionSchema", () => {
  // A card is sandboxed HTML any MCP server can supply, so a blank required field has to be
  // rejected here. Letting it through leaves a button that silently does nothing when clicked.
  it.each([
    ["a blank compose prompt", { kind: "compose", prompt: "   " }],
    ["a missing space id", { kind: "open_space", channel_id: "" }],
    [
      "a missing canvas id",
      { kind: "open_canvas", channel_id: "chan", canvas_id: "" },
    ],
    [
      "a blank canvas channel id",
      { kind: "open_canvas", channel_id: "  ", canvas_id: "dash" },
    ],
    ["an unknown verb", { kind: "open_website", url: "https://evil.example" }],
  ])("rejects %s", (_name, action) => {
    expect(mcpAppActionSchema.safeParse(action).success).toBe(false);
  });

  it("drops a label rather than carrying it into a link", () => {
    const parsed = mcpAppActionSchema.parse({
      kind: "open_space",
      channel_id: "chan",
      label: "Open the space",
    });

    expect(parsed).toEqual({ kind: "open_space", channel_id: "chan" });
  });

  it("keeps an optional repo but drops a blank one", () => {
    expect(
      mcpAppActionSchema.parse({
        kind: "compose",
        prompt: "Do it",
        repo: "posthog/posthog",
      }),
    ).toEqual({ kind: "compose", prompt: "Do it", repo: "posthog/posthog" });
    expect(
      mcpAppActionSchema.safeParse({
        kind: "compose",
        prompt: "Do it",
        repo: "  ",
      }).success,
    ).toBe(false);
  });
});

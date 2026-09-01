import { describe, expect, it } from "vitest";
import {
  LEGACY_RESOURCE_URI_META_KEY,
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

import { describe, expect, it } from "vitest";
import { boundPersistedMcpResult } from "./call-tool-result";

describe("boundPersistedMcpResult", () => {
  it("passes a result within the limit through unchanged, nulls stripped", () => {
    const bounded = boundPersistedMcpResult(
      {
        content: [{ type: "text", text: "42 rows" }],
        structuredContent: null,
        _meta: { ui: { resourceUri: "ui://posthog/chart.html" } },
      },
      500,
    );
    expect(bounded).toEqual({
      content: [{ type: "text", text: "42 rows" }],
      _meta: { ui: { resourceUri: "ui://posthog/chart.html" } },
    });
  });

  it("replaces an oversized result with the marker and the UI routing metadata", () => {
    const bounded = boundPersistedMcpResult(
      {
        content: [{ type: "text", text: "x".repeat(200) }],
        structuredContent: { rows: "y".repeat(200) },
        isError: false,
        _meta: {
          ui: { resourceUri: "ui://posthog/chart.html" },
          "ui/resourceUri": "ui://posthog/chart.html",
          vendor: { blob: "z".repeat(200) },
        },
      },
      100,
    );
    expect(bounded).toEqual({
      content: [{ type: "text", text: expect.stringContaining("too large") }],
      isError: false,
      _meta: {
        ui: { resourceUri: "ui://posthog/chart.html" },
        "ui/resourceUri": "ui://posthog/chart.html",
      },
    });
  });

  it("drops the routing metadata too when it is itself oversized", () => {
    const bounded = boundPersistedMcpResult(
      {
        content: [{ type: "text", text: "x".repeat(200) }],
        _meta: { ui: { resourceUri: "u".repeat(200) } },
      },
      100,
    );
    expect(bounded).toEqual({
      content: [{ type: "text", text: expect.stringContaining("too large") }],
    });
  });

  it("omits isError when the server sent a non-boolean value", () => {
    const bounded = boundPersistedMcpResult(
      {
        content: [{ type: "text", text: "x".repeat(200) }],
        isError: "y".repeat(50),
      },
      100,
    );
    expect(bounded).not.toHaveProperty("isError");
  });
});

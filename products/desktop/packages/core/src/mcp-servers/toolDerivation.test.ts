import type { McpInstallationTool } from "@posthog/api-client/types";
import { describe, expect, it } from "vitest";
import {
  countActiveTools,
  countRemovedTools,
  countToolsByApproval,
  filterToolsByName,
  sortToolsForDisplay,
} from "./toolDerivation";

function tool(
  name: string,
  overrides: Partial<McpInstallationTool> = {},
): McpInstallationTool {
  return {
    id: `tool-${name}`,
    tool_name: name,
    display_name: name,
    description: "",
    input_schema: {},
    approval_state: "needs_approval",
    last_seen_at: "2026-01-01T00:00:00Z",
    removed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("countToolsByApproval", () => {
  it("tallies non-removed tools by approval state", () => {
    const counts = countToolsByApproval([
      tool("a", { approval_state: "approved" }),
      tool("b", { approval_state: "approved" }),
      tool("c", { approval_state: "do_not_use" }),
      tool("d", { approval_state: "approved", removed_at: "2026-04-01" }),
    ]);
    expect(counts.approved).toBe(2);
    expect(counts.do_not_use).toBe(1);
  });
});

describe("sortToolsForDisplay", () => {
  it("sorts active before removed, then alphabetically", () => {
    const out = sortToolsForDisplay([
      tool("zebra"),
      tool("apple", { removed_at: "2026-04-01" }),
      tool("mango"),
    ]);
    expect(out.map((t) => t.tool_name)).toEqual(["mango", "zebra", "apple"]);
  });
});

describe("filterToolsByName", () => {
  it("substring-matches case-insensitively, empty returns all", () => {
    const tools = [tool("readFile"), tool("writeFile"), tool("listDir")];
    expect(filterToolsByName(tools, "file").map((t) => t.tool_name)).toEqual([
      "readFile",
      "writeFile",
    ]);
    expect(filterToolsByName(tools, "")).toHaveLength(3);
  });
});

describe("count helpers", () => {
  it("counts active and removed", () => {
    const tools = [tool("a"), tool("b", { removed_at: "2026-04-01" })];
    expect(countActiveTools(tools)).toBe(1);
    expect(countRemovedTools(tools)).toBe(1);
  });
});

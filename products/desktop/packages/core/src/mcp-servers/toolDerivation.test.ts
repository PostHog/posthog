import type { McpInstallationTool } from "@posthog/api-client/types";
import { describe, expect, it } from "vitest";
import {
  countActiveTools,
  countRemovedTools,
  countToolsByApproval,
  filterToolsByName,
  groupToolsByReadOnly,
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
    team_state: null,
    locked: false,
    decided_by: "default",
    is_read_only: false,
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

describe("groupToolsByReadOnly", () => {
  it("splits tools into read-only and write/delete groups, preserving order", () => {
    const tools = [
      tool("create_ticket", { is_read_only: false }),
      tool("list_tickets", { is_read_only: true }),
      tool("delete_ticket", { is_read_only: false }),
      tool("search_tickets", { is_read_only: true }),
    ];
    const { readOnly, writeOrDelete } = groupToolsByReadOnly(tools);
    expect(readOnly.map((t) => t.tool_name)).toEqual([
      "list_tickets",
      "search_tickets",
    ]);
    expect(writeOrDelete.map((t) => t.tool_name)).toEqual([
      "create_ticket",
      "delete_ticket",
    ]);
  });

  it("treats a missing is_read_only as write/delete", () => {
    const { readOnly, writeOrDelete } = groupToolsByReadOnly([tool("alpha")]);
    expect(readOnly).toHaveLength(0);
    expect(writeOrDelete).toHaveLength(1);
  });
});

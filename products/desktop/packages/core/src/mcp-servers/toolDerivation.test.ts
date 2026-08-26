import type { McpInstallationTool } from "@posthog/api-client/types";
import { describe, expect, it } from "vitest";
import {
  categorizeTool,
  countActiveTools,
  countRemovedTools,
  countToolsByApproval,
  filterToolsByName,
  groupToolsByCategory,
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

describe("categorizeTool", () => {
  it("categorizes read operations", () => {
    expect(categorizeTool("getFile")).toBe("read");
    expect(categorizeTool("listFiles")).toBe("read");
    expect(categorizeTool("readDocument")).toBe("read");
    expect(categorizeTool("searchUsers")).toBe("read");
    expect(categorizeTool("findItem")).toBe("read");
    expect(categorizeTool("queryDatabase")).toBe("read");
    expect(categorizeTool("fetchData")).toBe("read");
    expect(categorizeTool("checkStatus")).toBe("read");
  });

  it("categorizes write operations", () => {
    expect(categorizeTool("createFile")).toBe("write");
    expect(categorizeTool("updateRecord")).toBe("write");
    expect(categorizeTool("deleteItem")).toBe("write");
    expect(categorizeTool("removeUser")).toBe("write");
    expect(categorizeTool("writeDocument")).toBe("write");
    expect(categorizeTool("editContent")).toBe("write");
    expect(categorizeTool("sendEmail")).toBe("write");
    expect(categorizeTool("executeCommand")).toBe("write");
  });

  it("defaults to write for unknown prefixes", () => {
    expect(categorizeTool("unknownOperation")).toBe("write");
    expect(categorizeTool("customAction")).toBe("write");
  });

  it("is case-insensitive", () => {
    expect(categorizeTool("GET_FILE")).toBe("read");
    expect(categorizeTool("Create_Record")).toBe("write");
  });
});

describe("groupToolsByCategory", () => {
  it("groups tools by read and write categories", () => {
    const tools = [
      tool("getFile"),
      tool("createFile"),
      tool("listItems"),
      tool("deleteItem"),
    ];
    const groups = groupToolsByCategory(tools);
    expect(groups).toHaveLength(2);
    expect(groups[0].category).toBe("read");
    expect(groups[0].tools.map((t) => t.tool_name)).toEqual(["getFile", "listItems"]);
    expect(groups[1].category).toBe("write");
    expect(groups[1].tools.map((t) => t.tool_name)).toEqual(["createFile", "deleteItem"]);
  });

  it("excludes removed tools", () => {
    const tools = [
      tool("getFile"),
      tool("deletedFile", { removed_at: "2026-04-01" }),
    ];
    const groups = groupToolsByCategory(tools);
    expect(groups).toHaveLength(1);
    expect(groups[0].tools).toHaveLength(1);
    expect(groups[0].tools[0].tool_name).toBe("getFile");
  });

  it("returns empty array for no tools", () => {
    expect(groupToolsByCategory([])).toEqual([]);
  });

  it("returns only read group when all tools are read", () => {
    const tools = [tool("getFile"), tool("listItems")];
    const groups = groupToolsByCategory(tools);
    expect(groups).toHaveLength(1);
    expect(groups[0].category).toBe("read");
  });

  it("returns only write group when all tools are write", () => {
    const tools = [tool("createFile"), tool("deleteItem")];
    const groups = groupToolsByCategory(tools);
    expect(groups).toHaveLength(1);
    expect(groups[0].category).toBe("write");
  });
});

import type { McpRecommendedServer } from "@posthog/api-client/types";
import { describe, expect, it } from "vitest";
import { filterServersByCategory, filterServersByQuery } from "./filters";

function server(
  overrides: Partial<McpRecommendedServer>,
): McpRecommendedServer {
  return {
    id: "test-id",
    name: "Test",
    url: "https://example.com/mcp",
    description: "",
    auth_type: "oauth",
    ...overrides,
  } as McpRecommendedServer;
}

describe("filterServersByCategory", () => {
  const all = [
    server({ id: "a", category: "dev", name: "Alpha" }),
    server({ id: "b", category: "data", name: "Beta" }),
    server({ id: "c", category: "dev", name: "Gamma" }),
    server({ id: "d", name: "Delta" }), // no category
  ];

  it("returns everything when category is 'all'", () => {
    expect(filterServersByCategory(all, "all")).toHaveLength(4);
  });

  it("filters down to the exact category", () => {
    const out = filterServersByCategory(all, "dev");
    expect(out.map((s) => s.id).sort()).toEqual(["a", "c"]);
  });

  it("returns empty when nothing matches", () => {
    expect(filterServersByCategory(all, "infra")).toEqual([]);
  });
});

describe("filterServersByQuery", () => {
  const all = [
    server({ id: "a", name: "Linear", description: "Ticket tracker" }),
    server({ id: "b", name: "GitHub", description: "Code hosting" }),
    server({
      id: "c",
      name: "Notion",
      description: "Docs and knowledge base",
    }),
  ];

  it("returns all when query is empty or whitespace", () => {
    expect(filterServersByQuery(all, "")).toHaveLength(3);
    expect(filterServersByQuery(all, "   ")).toHaveLength(3);
  });

  it("matches against name", () => {
    expect(filterServersByQuery(all, "linear").map((s) => s.id)).toEqual(["a"]);
  });

  it("matches against description", () => {
    expect(filterServersByQuery(all, "tracker").map((s) => s.id)).toEqual([
      "a",
    ]);
  });

  it("is case insensitive", () => {
    expect(filterServersByQuery(all, "NOTION").map((s) => s.id)).toEqual(["c"]);
  });

  it("returns empty when nothing matches", () => {
    expect(filterServersByQuery(all, "zzz")).toEqual([]);
  });
});

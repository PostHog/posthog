import { describe, expect, it } from "vitest";
import { isMcpToolName, parseMcpToolName } from "./mcpToolName";

describe("isMcpToolName", () => {
  it("accepts a well-formed MCP tool name", () => {
    expect(isMcpToolName("mcp__github__create_issue")).toBe(true);
  });

  it("accepts tool names with extra underscores in the tool segment", () => {
    expect(isMcpToolName("mcp__github__list_pull_requests")).toBe(true);
  });

  it("rejects non-MCP tool names", () => {
    expect(isMcpToolName("read_file")).toBe(false);
    expect(isMcpToolName("Bash")).toBe(false);
    expect(isMcpToolName("")).toBe(false);
    expect(isMcpToolName(null)).toBe(false);
    expect(isMcpToolName(undefined)).toBe(false);
  });

  it("rejects malformed prefixes", () => {
    expect(isMcpToolName("mcp_github__tool")).toBe(false);
    expect(isMcpToolName("mcp__github")).toBe(false); // no second separator
    expect(isMcpToolName("mcp__")).toBe(false);
  });
});

describe("parseMcpToolName", () => {
  it("splits server and tool", () => {
    expect(parseMcpToolName("mcp__linear__create_issue")).toEqual({
      serverName: "linear",
      toolName: "create_issue",
    });
  });

  it("keeps double-underscore tool names intact on the tool side", () => {
    expect(parseMcpToolName("mcp__db__select__count")).toEqual({
      serverName: "db",
      toolName: "select__count",
    });
  });

  it("returns null for invalid names", () => {
    expect(parseMcpToolName("read_file")).toBeNull();
    expect(parseMcpToolName("mcp__only-server")).toBeNull();
    expect(parseMcpToolName(null)).toBeNull();
  });
});

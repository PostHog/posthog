import { describe, expect, it } from "vitest";
import {
  formatPosthogExecBody,
  getPostHogExecDisplay,
  isPostHogExecTool,
} from "./posthogExecDisplay";

describe("isPostHogExecTool", () => {
  it("matches the bare posthog exec tool", () => {
    expect(isPostHogExecTool("mcp__posthog__exec")).toBe(true);
  });

  it("matches plugin-prefixed variants", () => {
    expect(isPostHogExecTool("mcp__posthog_posthog__exec")).toBe(true);
    expect(isPostHogExecTool("mcp__plugin_posthog_posthog__exec")).toBe(true);
    expect(isPostHogExecTool("mcp__posthog_cloud__exec")).toBe(true);
  });

  it("rejects other MCP tools", () => {
    expect(isPostHogExecTool("mcp__posthog__list")).toBe(false);
    expect(isPostHogExecTool("mcp__other__exec")).toBe(false);
    expect(isPostHogExecTool("Bash")).toBe(false);
  });
});

describe("getPostHogExecDisplay", () => {
  it("collapses `call <tool>` to the bare sub-tool label", () => {
    expect(getPostHogExecDisplay({ command: "call experiment-list" })).toEqual({
      label: "experiment-list",
      input: undefined,
    });
  });

  it("uses the JSON args portion as input", () => {
    expect(
      getPostHogExecDisplay({
        command: 'call execute-sql {"query":"SELECT 1"}',
      }),
    ).toEqual({
      label: "execute-sql",
      input: '{"query":"SELECT 1"}',
    });
  });

  it("formats `info <tool>` with no args", () => {
    expect(getPostHogExecDisplay({ command: "info execute-sql" })).toEqual({
      label: "Read execute-sql",
      input: undefined,
    });
  });

  it("formats `schema <tool> <field_path>` as a dotted locator", () => {
    expect(
      getPostHogExecDisplay({
        command: "schema query-trends series",
      }),
    ).toEqual({
      label: "Inspect query-trends.series",
      input: undefined,
    });
  });

  it("uses the regex pattern as input for search", () => {
    expect(getPostHogExecDisplay({ command: "search query-" })).toEqual({
      label: "Search tools",
      input: "query-",
    });
  });

  it("formats bare `tools`", () => {
    expect(getPostHogExecDisplay({ command: "tools" })).toEqual({
      label: "List tools",
      input: undefined,
    });
  });

  it("prefers an explicit object `input` over command-embedded args", () => {
    expect(
      getPostHogExecDisplay({
        command: "call execute-sql",
        input: { query: "SELECT 1" },
      }),
    ).toEqual({
      label: "execute-sql",
      input: '{"query":"SELECT 1"}',
    });
  });

  it("returns null for malformed input", () => {
    expect(getPostHogExecDisplay(undefined)).toBeNull();
    expect(getPostHogExecDisplay({})).toBeNull();
    expect(getPostHogExecDisplay({ command: "call" })).toBeNull();
  });
});

describe("formatPosthogExecBody", () => {
  it("pretty-prints JSON object payloads", () => {
    expect(formatPosthogExecBody('{"id":3}')).toBe('{\n  "id": 3\n}');
  });

  it("returns non-JSON strings unchanged", () => {
    expect(formatPosthogExecBody("query-")).toBe("query-");
  });

  it("returns JSON primitives unchanged", () => {
    expect(formatPosthogExecBody("42")).toBe("42");
  });
});

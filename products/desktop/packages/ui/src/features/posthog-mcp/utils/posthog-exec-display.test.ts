import { describe, expect, it } from "vitest";
import {
  formatPosthogExecBody,
  getPostHogExecDisplay,
  isPostHogExecTool,
} from "./posthog-exec-display";

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
  describe("call verb", () => {
    it("collapses `call <tool>` to the bare sub-tool label", () => {
      expect(
        getPostHogExecDisplay({ command: "call experiment-list" }),
      ).toEqual({
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

    it("handles `call --json <tool> {json}`", () => {
      expect(
        getPostHogExecDisplay({
          command: 'call --json experiment-update {"id":1}',
        }),
      ).toEqual({
        label: "experiment-update",
        input: '{"id":1}',
      });
    });
  });

  describe("info verb", () => {
    it("formats `info <tool>` with no args", () => {
      expect(getPostHogExecDisplay({ command: "info execute-sql" })).toEqual({
        label: "Read execute-sql",
        input: undefined,
      });
    });

    it("falls back to a generic label when no tool given", () => {
      expect(getPostHogExecDisplay({ command: "info" })).toEqual({
        label: "Read tool",
        input: undefined,
      });
    });
  });

  describe("schema verb", () => {
    it("formats `schema <tool>` (no field path) as field summary", () => {
      expect(getPostHogExecDisplay({ command: "schema query-trends" })).toEqual(
        {
          label: "Inspect query-trends fields",
          input: undefined,
        },
      );
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

    it("supports dotted field paths", () => {
      expect(
        getPostHogExecDisplay({
          command: "schema query-trends breakdownFilter.breakdowns",
        }),
      ).toEqual({
        label: "Inspect query-trends.breakdownFilter.breakdowns",
        input: undefined,
      });
    });
  });

  describe("search verb", () => {
    it("uses the regex pattern as input", () => {
      expect(getPostHogExecDisplay({ command: "search query-" })).toEqual({
        label: "Search tools",
        input: "query-",
      });
    });

    it("falls back to bare `Search tools` when no pattern given", () => {
      expect(getPostHogExecDisplay({ command: "search" })).toEqual({
        label: "Search tools",
        input: undefined,
      });
    });
  });

  describe("tools verb", () => {
    it("formats bare `tools`", () => {
      expect(getPostHogExecDisplay({ command: "tools" })).toEqual({
        label: "List tools",
        input: undefined,
      });
    });
  });

  describe("explicit input field", () => {
    it("prefers an explicit string `input` over command-embedded args (call)", () => {
      expect(
        getPostHogExecDisplay({
          command: 'call execute-sql {"query":"SELECT 1"}',
          input: "SELECT 2",
        }),
      ).toEqual({ label: "execute-sql", input: "SELECT 2" });
    });

    it("prefers an explicit object `input` (serialised) over command-embedded args (call)", () => {
      expect(
        getPostHogExecDisplay({
          command: "call execute-sql",
          input: { query: "SELECT 1" },
        }),
      ).toEqual({ label: "execute-sql", input: '{"query":"SELECT 1"}' });
    });

    it("folds explicit `input` into the schema dotted locator", () => {
      expect(
        getPostHogExecDisplay({
          command: "schema query-trends",
          input: "series.0",
        }),
      ).toEqual({ label: "Inspect query-trends.series.0", input: undefined });
    });

    it("ignores empty-string explicit input and falls back to command args", () => {
      expect(
        getPostHogExecDisplay({
          command: 'call execute-sql {"query":"x"}',
          input: "   ",
        }),
      ).toEqual({ label: "execute-sql", input: '{"query":"x"}' });
    });
  });

  describe("malformed / unsupported", () => {
    it("returns null for unknown verbs", () => {
      expect(getPostHogExecDisplay({ command: "unknown-verb foo" })).toBeNull();
      expect(getPostHogExecDisplay({ command: "list" })).toBeNull();
      expect(getPostHogExecDisplay({ command: "run something" })).toBeNull();
    });

    it("returns null for missing or malformed input", () => {
      expect(getPostHogExecDisplay(undefined)).toBeNull();
      expect(getPostHogExecDisplay(null)).toBeNull();
      expect(getPostHogExecDisplay({})).toBeNull();
      expect(getPostHogExecDisplay({ command: 42 })).toBeNull();
      expect(getPostHogExecDisplay({ command: "" })).toBeNull();
    });

    it("returns null for `call` with no sub-tool", () => {
      expect(getPostHogExecDisplay({ command: "call" })).toBeNull();
      expect(getPostHogExecDisplay({ command: "call   " })).toBeNull();
    });

    it("tolerates leading/trailing whitespace around the verb", () => {
      expect(getPostHogExecDisplay({ command: "  tools  " })).toEqual({
        label: "List tools",
        input: undefined,
      });
      expect(
        getPostHogExecDisplay({ command: "  call execute-sql  " }),
      ).toEqual({ label: "execute-sql", input: undefined });
    });
  });
});

describe("formatPosthogExecBody", () => {
  it("returns undefined for empty input", () => {
    expect(formatPosthogExecBody(undefined)).toBeUndefined();
    expect(formatPosthogExecBody("")).toBeUndefined();
  });

  it("pretty-prints JSON object payloads", () => {
    expect(formatPosthogExecBody('{"id":3}')).toBe('{\n  "id": 3\n}');
  });

  it("pretty-prints JSON array payloads", () => {
    expect(formatPosthogExecBody("[1,2]")).toBe("[\n  1,\n  2\n]");
  });

  it("returns non-JSON strings unchanged (e.g. search regex)", () => {
    expect(formatPosthogExecBody("query-")).toBe("query-");
  });

  it("returns malformed JSON unchanged", () => {
    expect(formatPosthogExecBody('{"id":')).toBe('{"id":');
  });

  it("returns JSON primitives unchanged (not pretty-printable)", () => {
    expect(formatPosthogExecBody("42")).toBe("42");
    expect(formatPosthogExecBody('"hello"')).toBe('"hello"');
  });
});

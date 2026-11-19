import { describe, expect, it } from "vitest";
import { createPiToolCallRecord, parsePiMcpCallDetails } from "./pi-tool-call";

describe("createPiToolCallRecord", () => {
  it.each([
    ["read", "Read"],
    ["bash", "Bash"],
    ["edit", "Edit"],
    ["write", "Write"],
    ["grep", "Grep"],
    ["find", "Glob"],
    ["ls", "LS"],
  ])("names the %s built-in %s on _meta.posthog", (name, toolName) => {
    expect(
      createPiToolCallRecord({ id: "t", name, arguments: {} }, "pending")._meta,
    ).toEqual({ posthog: { toolName } });
  });

  it("carries the proxied MCP call on _meta.posthog", () => {
    expect(
      createPiToolCallRecord(
        {
          id: "t",
          name: "mcp",
          arguments: { tool: "linear_create_issue", args: '{"title":"x"}' },
        },
        "pending",
      )._meta,
    ).toEqual({
      posthog: {
        toolName: "mcp",
        mcpProxy: {
          kind: "tool",
          name: "linear_create_issue",
          args: '{"title":"x"}',
        },
      },
    });
  });

  it("keeps an unknown tool's own name", () => {
    expect(
      createPiToolCallRecord(
        { id: "t", name: "set_current_work", arguments: {} },
        "pending",
      )._meta,
    ).toEqual({ posthog: { toolName: "set_current_work" } });
  });
});

describe("parsePiMcpCallDetails", () => {
  it.each(["mcp_posthog_exec", "mcp__posthog__exec"])(
    "normalizes a direct PostHog exec call: %s",
    (name) => {
      expect(
        parsePiMcpCallDetails(name, {
          command: "call feature-flag-get-all",
        }),
      ).toEqual({
        kind: "tool",
        name,
        args: '{"command":"call feature-flag-get-all"}',
      });
    },
  );

  it("does not normalize other MCP tools", () => {
    expect(
      parsePiMcpCallDetails("mcp__posthog__feature-flag-get-all", {
        limit: 5,
      }),
    ).toBeUndefined();
  });

  it("keeps proxy search details", () => {
    expect(parsePiMcpCallDetails("mcp", { search: "feature flags" })).toEqual({
      kind: "search",
      query: "feature flags",
    });
  });
});

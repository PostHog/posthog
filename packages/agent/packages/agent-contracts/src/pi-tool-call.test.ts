import { describe, expect, it } from "vitest";
import { parsePiMcpCallDetails } from "./pi-tool-call";

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

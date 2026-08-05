import { readMcpToolDescriptor } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  buildPiMcpPermissionToolCall,
  PI_MCP_PERMISSION_OPTIONS,
} from "./piMcpPermission";

describe("Pi MCP permission", () => {
  it("preserves the MCP descriptor and arguments for permission rendering", () => {
    const toolCall = buildPiMcpPermissionToolCall({
      requestId: "request-1",
      serverName: "Cloudflare",
      toolName: "search",
      installationId: "installation-1",
      arguments: { query: "workers" },
      description: "Search Cloudflare resources",
    });

    expect(readMcpToolDescriptor(toolCall._meta)).toEqual({
      server: "Cloudflare",
      tool: "search",
    });
    expect(toolCall.rawInput).toEqual({ query: "workers" });
  });

  it("does not offer one-time approval when approval must persist", () => {
    expect(PI_MCP_PERMISSION_OPTIONS.map((option) => option.optionId)).toEqual([
      "allow_always",
      "reject",
    ]);
  });
});

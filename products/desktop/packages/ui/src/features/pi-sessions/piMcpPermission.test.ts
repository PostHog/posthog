import {
  MCP_TOOL_PERMISSION_OPTIONS,
  readMcpInstallationId,
  readMcpToolDescriptor,
} from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { buildPiMcpPermissionToolCall } from "./piMcpPermission";

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
    expect(readMcpInstallationId(toolCall._meta)).toBe("installation-1");
    expect(toolCall.rawInput).toEqual({ query: "workers" });
  });

  it("does not offer one-time approval when approval must persist", () => {
    expect(
      MCP_TOOL_PERMISSION_OPTIONS.map((option) => option.optionId),
    ).toEqual(["allow_always", "reject"]);
  });
});

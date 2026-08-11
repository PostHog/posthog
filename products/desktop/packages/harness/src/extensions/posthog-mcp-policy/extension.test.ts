import type {
  ExtensionAPI,
  ToolCallEvent,
} from "@earendil-works/pi-coding-agent";
import type { McpToolPermissionDecision } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { createPosthogMcpPolicyExtension } from "./extension";

function setup(approvalState: "approved" | "needs_approval" | "do_not_use") {
  let handler: ((event: ToolCallEvent) => Promise<unknown>) | undefined;
  const pi = {
    on: vi.fn((event: string, callback: typeof handler) => {
      if (event === "tool_call") {
        handler = callback;
      }
    }),
  } as unknown as ExtensionAPI;
  const requestMcpToolPermission = vi.fn<
    () => Promise<McpToolPermissionDecision>
  >(async () => "allow");

  createPosthogMcpPolicyExtension({
    mcpToolPolicies: [
      {
        serverName: "Cloudflare",
        toolName: "search",
        installationId: "installation-1",
        approvalState,
      },
    ],
    requestMcpToolPermission,
  })(pi);

  return {
    requestMcpToolPermission,
    call: (toolName: string, input: Record<string, unknown> = {}) =>
      handler?.({
        type: "tool_call",
        toolCallId: "call-1",
        toolName,
        input,
      } as ToolCallEvent),
  };
}

describe("posthog MCP policy extension", () => {
  it("allows approved tools without prompting", async () => {
    const runtime = setup("approved");

    await expect(
      runtime.call("mcp_Cloudflare_search"),
    ).resolves.toBeUndefined();
    expect(runtime.requestMcpToolPermission).not.toHaveBeenCalled();
  });

  it("prompts again after a one-time approval", async () => {
    const runtime = setup("needs_approval");

    await expect(
      runtime.call("mcp_Cloudflare_search"),
    ).resolves.toBeUndefined();
    await expect(
      runtime.call("mcp_Cloudflare_search"),
    ).resolves.toBeUndefined();
    expect(runtime.requestMcpToolPermission).toHaveBeenCalledTimes(2);
    expect(runtime.requestMcpToolPermission).toHaveBeenCalledWith({
      requestId: "call-1",
      serverName: "Cloudflare",
      toolName: "search",
      installationId: "installation-1",
      arguments: {},
    });
  });

  it("remembers an always-allow approval", async () => {
    const runtime = setup("needs_approval");
    runtime.requestMcpToolPermission.mockResolvedValue("allow_always");

    await runtime.call("mcp_Cloudflare_search");
    await runtime.call("mcp_Cloudflare_search");

    expect(runtime.requestMcpToolPermission).toHaveBeenCalledOnce();
  });

  it("blocks a rejected approval", async () => {
    const runtime = setup("needs_approval");
    runtime.requestMcpToolPermission.mockResolvedValue("reject");

    await expect(runtime.call("mcp_Cloudflare_search")).resolves.toEqual({
      block: true,
      reason: "Permission rejected for Cloudflare.search.",
    });
  });

  it("blocks disabled tools", async () => {
    const runtime = setup("do_not_use");

    await expect(runtime.call("mcp_Cloudflare_search")).resolves.toEqual({
      block: true,
      reason: "The Cloudflare tool search is disabled in PostHog MCP settings.",
    });
  });

  it("handles calls through the MCP proxy tool", async () => {
    const runtime = setup("needs_approval");

    await runtime.call("mcp", {
      tool: "mcp_Cloudflare_search",
      args: '{"query":"workers"}',
    });

    expect(runtime.requestMcpToolPermission).toHaveBeenCalledWith(
      expect.objectContaining({ arguments: { query: "workers" } }),
    );
  });
});

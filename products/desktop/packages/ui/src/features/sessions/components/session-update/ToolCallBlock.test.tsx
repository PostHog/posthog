import { ServiceProvider } from "@posthog/di/react";
import { posthogToolMeta } from "@posthog/shared";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { Container } from "inversify";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { MCP_TOOL_BLOCK_COMPONENT } from "./identifiers";
import { ToolCallBlock } from "./ToolCallBlock";
import type { ToolViewProps } from "./toolCallUtils";

// EditToolView's leaf renderers reach outside the unit under test: FileMentionChip
// pulls workspace/tRPC context, and CodePreview mounts a web component that needs
// a real CSSStyleSheet. The edit-routing test only cares that ToolCallBlock
// dispatched to EditToolView, so stub both to their load-bearing inputs.
vi.mock("./FileMentionChip", () => ({
  FileMentionChip: ({ filePath }: { filePath: string }) => (
    <span>{filePath}</span>
  ),
}));
vi.mock("./CodePreview", () => ({
  CodePreview: () => <span>code-preview</span>,
}));

function renderBlock(
  toolCall: ToolCall,
  mcpToolBlock?: (props: ToolViewProps & { mcpToolName: string }) => ReactNode,
) {
  const container = new Container();
  if (mcpToolBlock) {
    container.bind(MCP_TOOL_BLOCK_COMPONENT).toConstantValue(mcpToolBlock);
  }
  return render(
    <ServiceProvider container={container}>
      <Theme>
        <ToolCallBlock toolCall={toolCall} turnComplete />
      </Theme>
    </ServiceProvider>,
  );
}

describe("ToolCallBlock codex routing", () => {
  it("routes a codex MCP descriptor to the bound McpToolBlock with the canonical name", () => {
    const seen: { mcpToolName?: string } = {};
    const McpToolBlock = vi.fn(
      ({ mcpToolName }: ToolViewProps & { mcpToolName: string }) => {
        seen.mcpToolName = mcpToolName;
        return <div>mcp-block-rendered</div>;
      },
    );

    renderBlock(
      {
        toolCallId: "tc-mcp",
        title: "exec",
        kind: "other",
        status: "completed",
        rawInput: { query: "select 1" },
        _meta: posthogToolMeta({
          toolName: "mcp__posthog__exec",
          mcp: { server: "posthog", tool: "exec" },
        }),
      },
      McpToolBlock,
    );

    expect(screen.getByText("mcp-block-rendered")).toBeInTheDocument();
    expect(seen.mcpToolName).toBe("mcp__posthog__exec");
  });

  it("falls back to the generic tool view for an MCP call when no McpToolBlock is bound", () => {
    renderBlock({
      toolCallId: "tc-mcp-fallback",
      title: "exec",
      kind: "other",
      status: "completed",
      rawInput: { query: "select 1" },
      _meta: posthogToolMeta({
        toolName: "mcp__posthog__exec",
        mcp: { server: "posthog", tool: "exec" },
      }),
    });

    // The MCP branch renders the title in its header; assert it lands somewhere
    // (i.e. the call did not blow up unbound) without an MCP block present.
    expect(screen.getByText("exec")).toBeInTheDocument();
  });

  it("routes a codex edit tool call (no _meta) to the edit view with diff stats", () => {
    renderBlock({
      toolCallId: "tc-edit",
      title: "Edit a.ts",
      kind: "edit",
      status: "completed",
      content: [{ type: "diff", path: "a.ts", oldText: "x", newText: "y" }],
      locations: [{ path: "a.ts" }],
    });

    expect(screen.getByText("a.ts")).toBeInTheDocument();
    expect(screen.getByText("+1")).toBeInTheDocument();
    expect(screen.getByText("-1")).toBeInTheDocument();
  });

  it("routes a codex execute tool call (no _meta) to the execute view header", () => {
    renderBlock({
      toolCallId: "tc-exec",
      title: "run tests",
      kind: "execute",
      status: "completed",
      rawInput: { command: "pnpm test", description: "Run tests" },
      content: [{ type: "content", content: { type: "text", text: "ok" } }],
    });

    expect(screen.getByText("Run tests")).toBeInTheDocument();
    expect(screen.getByText("pnpm test")).toBeInTheDocument();
  });

  it("renders Codex orchestration calls as operations rather than subagents", () => {
    renderBlock({
      toolCallId: "tc-wait-agent",
      title: "Wait for subagents",
      kind: "other",
      status: "completed",
      _meta: posthogToolMeta({ toolName: "wait_agent" }),
    });

    expect(screen.getByText("Wait for subagents")).toBeInTheDocument();
    expect(screen.queryByText(/^Subagent/)).not.toBeInTheDocument();
  });
});

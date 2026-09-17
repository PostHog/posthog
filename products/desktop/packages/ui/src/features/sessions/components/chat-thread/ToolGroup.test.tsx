import { ServiceProvider } from "@posthog/di/react";
import { createPiToolCallRecord, posthogToolMeta } from "@posthog/shared";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { Container } from "inversify";
import { describe, expect, it } from "vitest";
import { ToolGroup } from "./ToolGroup";

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

function subagentItem(
  id: string,
  options: {
    status?: "completed" | "in_progress";
    turnComplete?: boolean;
    subagentCount?: number;
  } = {},
): SessionUpdateItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "tool_call",
      toolCallId: id,
      title: "Subagent",
      kind: "other",
      status: options.status ?? "completed",
      _meta: posthogToolMeta({ toolName: "spawn_agent" }),
      details: options.subagentCount
        ? {
            mode: "parallel",
            results: Array.from({ length: options.subagentCount }, () => ({
              agent: "Explore",
              task: "Inspect project files",
            })),
          }
        : undefined,
    },
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: options.turnComplete ?? true,
    },
  } as SessionUpdateItem;
}

function toolItem(
  id: string,
  options: {
    title: string;
    details?: unknown;
    toolMeta?: ReturnType<typeof posthogToolMeta>;
  },
): SessionUpdateItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "tool_call",
      toolCallId: id,
      title: options.title,
      kind: "other",
      status: "in_progress",
      details: options.details,
      _meta: options.toolMeta,
    },
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: false,
    },
  } as SessionUpdateItem;
}

function piToolItem(
  id: string,
  name: string,
  args: unknown,
): SessionUpdateItem {
  const toolCall = createPiToolCallRecord(
    { id, name, arguments: args },
    "in_progress",
  );
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "tool_call",
      toolCallId: id,
      ...toolCall,
    },
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: false,
    },
  } as SessionUpdateItem;
}

function thoughtItem(
  id: string,
  options: { thoughtComplete: boolean; turnComplete?: boolean },
): SessionUpdateItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "agent_thought_chunk",
      content: { type: "text", text: "weighing the options" },
    },
    thoughtComplete: options.thoughtComplete,
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: options.turnComplete ?? true,
    },
  } as SessionUpdateItem;
}

function renderGroup(items: SessionUpdateItem[]) {
  return render(
    <ServiceProvider container={new Container()}>
      <Theme>
        <ToolGroup items={items} />
      </Theme>
    </ServiceProvider>,
  );
}

describe("ToolGroup", () => {
  const running = { status: "in_progress", turnComplete: false } as const;

  // The row is one line standing in for a whole run, so what that line says is the contract: what
  // is happening while it runs, what it did once it settles.
  it.each([
    {
      name: "tallies the run once it settles",
      items: [subagentItem("spawn-1"), subagentItem("spawn-2")],
      expected: "Ran 2 subagents",
    },
    {
      name: "names the current tool while the run is active",
      items: [
        subagentItem("spawn-1", running),
        subagentItem("spawn-2", running),
      ],
      expected: "Subagents",
    },
    {
      name: "names an MCP proxy call while it is active",
      items: [
        piToolItem("mcp-call", "mcp", {
          tool: "mcp_posthog_query_trends",
          args: "{}",
        }),
      ],
      expected: "MCP: posthog query trends",
    },
    {
      name: "names an MCP search while it is active",
      items: [piToolItem("mcp-search", "mcp", { search: "dashboard metrics" })],
      expected: 'Searching MCP tools for "dashboard metrics"',
    },
    {
      name: "names a direct MCP tool while it is active",
      items: [piToolItem("mcp-direct", "mcp__posthog__query-trends", {})],
      expected: "MCP: posthog query trends",
    },
    {
      name: "uses the server and tool after MCP metadata arrives",
      items: [
        toolItem("mcp-metadata", {
          title: "mcp",
          toolMeta: posthogToolMeta({
            toolName: "mcp__posthog__query-trends",
            mcp: { server: "posthog", tool: "query-trends" },
          }),
        }),
      ],
      expected: "MCP: posthog / query-trends",
    },
    {
      name: "ignores malformed MCP display details",
      items: [
        toolItem("mcp-invalid", {
          title: "mcp",
          details: { kind: "tool", name: 42 },
        }),
      ],
      expected: "MCP",
    },
    {
      name: "reads as thinking while a trailing thought streams",
      items: [
        subagentItem("spawn-1", running),
        subagentItem("spawn-2", running),
        thoughtItem("thought-1", {
          thoughtComplete: false,
          turnComplete: false,
        }),
      ],
      expected: "Thinking…",
    },
  ])("$name", ({ items, expected }) => {
    renderGroup(items);
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("counts every parallel subagent in one tool call", () => {
    renderGroup([subagentItem("spawn-1", { subagentCount: 2 })]);

    expect(screen.getByText("Ran 2 subagents")).toBeInTheDocument();
  });

  it("starts collapsed", () => {
    renderGroup([subagentItem("spawn-1"), subagentItem("spawn-2")]);
    expect(screen.getAllByRole("button")[0]).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});

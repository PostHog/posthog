import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ToolCallView } from "./ToolCallView";

const ERROR_MARKER = "Sentinel error reason for testing";
const OUTPUT_MARKER = "Sentinel success output for testing";

function makeToolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    toolCallId: "tc-1",
    title: "do_something",
    kind: "other",
    status: "completed",
    rawInput: { foo: "bar" },
    ...overrides,
  };
}

function textContent(text: string): NonNullable<ToolCall["content"]> {
  return [{ type: "content", content: { type: "text", text } }];
}

function renderView(toolCall: ToolCall) {
  return render(
    <Theme>
      <ToolCallView toolCall={toolCall} expanded />
    </Theme>,
  );
}

describe("ToolCallView", () => {
  it.each([
    { status: "failed" as const, marker: ERROR_MARKER },
    { status: "completed" as const, marker: OUTPUT_MARKER },
  ])("renders content when status is $status", ({ status, marker }) => {
    renderView(makeToolCall({ status, content: textContent(marker) }));

    expect(screen.getByText(marker)).toBeInTheDocument();
  });

  it.each([
    {
      title: "mcp",
      details: { kind: "search", query: "business knowledge" },
      expected: "Search MCP tools",
    },
    {
      title: "mcp",
      details: {
        kind: "tool",
        name: "mcp_posthog_exec",
        args: JSON.stringify({ command: "call feature-flag-get-all" }),
      },
      expected: "posthog - feature-flag-get-all",
    },
    {
      title: "mcp__posthog__project-get",
      expected: "posthog - project get",
    },
    {
      title: "mcp",
      meta: {
        posthog: {
          toolName: "mcp",
          mcpProxy: {
            kind: "tool",
            name: "mcp_posthog_exec",
            args: JSON.stringify({ command: "schema feature-flag-get-all" }),
          },
        },
      },
      expected: "posthog - Inspect feature-flag-get-all fields",
    },
  ])(
    "shows a readable MCP tool label",
    ({ title, details, meta, expected }) => {
      renderView(makeToolCall({ title, details, _meta: meta }));

      expect(screen.getByText(expected)).toBeInTheDocument();
    },
  );
});

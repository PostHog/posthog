import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { McpToolView } from "./McpToolView";

const ERROR_MARKER = "Sentinel error reason for testing";
const OUTPUT_MARKER = "Sentinel success output for testing";

function makeToolCall(overrides: Partial<ToolCall> = {}): ToolCall {
  return {
    toolCallId: "tc-1",
    title: "posthog",
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
      <McpToolView toolCall={toolCall} mcpToolName="posthog__query" expanded />
    </Theme>,
  );
}

describe("McpToolView", () => {
  it.each([
    { status: "failed" as const, marker: ERROR_MARKER },
    { status: "completed" as const, marker: OUTPUT_MARKER },
  ])("renders content when status is $status", ({ status, marker }) => {
    renderView(makeToolCall({ status, content: textContent(marker) }));

    expect(screen.getByText(marker)).toBeInTheDocument();
  });
});

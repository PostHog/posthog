import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { McpToolBlock } from "./McpToolBlock";

describe("McpToolBlock", () => {
  it("selects the tasks-spawn renderer for the PostHog tool", () => {
    const toolCall: ToolCall = {
      toolCallId: "spawn-1",
      title: "tasks-spawn",
      kind: "other",
      status: "in_progress",
      rawInput: { title: "Implement focused fix", delegation_profile: "low" },
    };

    render(
      <Theme>
        <McpToolBlock
          toolCall={toolCall}
          mcpToolName="mcp__posthog__tasks-spawn"
        />
      </Theme>,
    );

    expect(screen.getByText("Spawn child task")).toBeInTheDocument();
    expect(screen.getByText("Implement focused fix")).toBeInTheDocument();
  });
});

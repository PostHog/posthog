import { ServiceProvider } from "@posthog/di/react";
import { posthogToolMeta } from "@posthog/shared";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { Container } from "inversify";
import { describe, expect, it } from "vitest";
import { ToolGroup } from "./ToolGroup";

function subagentItem(
  id: string,
  options: {
    status?: "completed" | "in_progress";
    turnComplete?: boolean;
  } = {},
): Extract<ConversationItem, { type: "session_update" }> {
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
    },
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: options.turnComplete ?? true,
    },
  } as Extract<ConversationItem, { type: "session_update" }>;
}

describe("ToolGroup", () => {
  it("shows the current tool name and context and starts collapsed", () => {
    render(
      <ServiceProvider container={new Container()}>
        <Theme>
          <ToolGroup
            tools={[subagentItem("spawn-1"), subagentItem("spawn-2")]}
          />
        </Theme>
      </ServiceProvider>,
    );

    expect(screen.getByText("Subagents")).toBeInTheDocument();
    expect(screen.getByText("Subagent")).toBeInTheDocument();
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("shows the current tool while a batch is active", () => {
    render(
      <ServiceProvider container={new Container()}>
        <Theme>
          <ToolGroup
            tools={[
              subagentItem("spawn-1", {
                status: "in_progress",
                turnComplete: false,
              }),
              subagentItem("spawn-2", {
                status: "in_progress",
                turnComplete: false,
              }),
            ]}
          />
        </Theme>
      </ServiceProvider>,
    );

    expect(screen.getByText("Subagents")).toBeInTheDocument();
    expect(screen.getByText("Subagent")).toBeInTheDocument();
    expect(screen.getByRole("button")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});

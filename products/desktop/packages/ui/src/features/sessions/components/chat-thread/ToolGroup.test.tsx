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
  it("labels Codex spawn batches as subagents", () => {
    render(
      <ServiceProvider container={new Container()}>
        <Theme>
          <ToolGroup
            tools={[subagentItem("spawn-1"), subagentItem("spawn-2")]}
          />
        </Theme>
      </ServiceProvider>,
    );

    expect(screen.getByText("Used Subagents")).toBeInTheDocument();
  });

  it("labels unresolved Codex spawn batches as active subagents", () => {
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

    expect(screen.getByText("Using Subagents")).toBeInTheDocument();
  });
});

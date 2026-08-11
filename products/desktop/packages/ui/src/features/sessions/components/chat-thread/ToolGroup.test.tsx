import { ServiceProvider } from "@posthog/di/react";
import { posthogToolMeta } from "@posthog/shared";
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
    },
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: options.turnComplete ?? true,
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
      expected: "2 subagents",
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

  it("starts collapsed", () => {
    renderGroup([subagentItem("spawn-1"), subagentItem("spawn-2")]);
    expect(screen.getAllByRole("button")[0]).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});

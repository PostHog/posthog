import { ServiceProvider } from "@posthog/di/react";
import type {
  ConversationItem,
  TurnContext,
} from "@posthog/ui/features/sessions/components/buildConversationItems";
import { ChatThreadChromeProvider } from "@posthog/ui/features/sessions/components/chat-thread/chatThreadChrome";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { Container } from "inversify";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    deepLink: {
      openAgentAction: {
        mutationOptions: () => ({ mutationFn: vi.fn() }),
      },
    },
  }),
}));

import { SubagentToolView } from "./SubagentToolView";

describe("SubagentToolView", () => {
  it("keeps action buttons visible while the subagent row is collapsed", () => {
    const action: ToolCall = {
      toolCallId: "action",
      title: "show_actions",
      kind: "other",
      status: "completed",
      rawInput: {
        actions: [
          {
            kind: "compose",
            label: "Start a follow-up task",
            prompt: "Review the test commands.",
          },
        ],
      },
      _meta: {
        claudeCode: {
          toolName: "mcp__posthog-code-tools__show_actions",
          parentToolCallId: "agent",
        },
      },
    };
    const read: ToolCall = {
      toolCallId: "read",
      title: "Read package.json",
      kind: "read",
      status: "completed",
    };
    const turnContext: TurnContext = {
      toolCalls: new Map([
        [read.toolCallId, read],
        [action.toolCallId, action],
      ]),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete: true,
    };
    const childItems: ConversationItem[] = [
      {
        type: "session_update",
        id: "child-read",
        update: { ...read, sessionUpdate: "tool_call" },
        turnContext,
      },
      {
        type: "session_update",
        id: "child-action",
        update: { ...action, sessionUpdate: "tool_call" },
        turnContext,
      },
    ];

    render(
      <QueryClientProvider client={new QueryClient()}>
        <ServiceProvider container={new Container()}>
          <ChatThreadChromeProvider value>
            <SubagentToolView
              toolCall={{
                toolCallId: "agent",
                title: "Test nested actions",
                kind: "think",
                status: "completed",
              }}
              childItems={childItems}
              turnContext={turnContext}
              turnComplete
            />
          </ChatThreadChromeProvider>
        </ServiceProvider>
      </QueryClientProvider>,
    );

    expect(
      screen.getByRole("button", { name: "Start a follow-up task" }),
    ).toBeVisible();
    expect(document.querySelector('[aria-expanded="false"]')).not.toBeNull();
  });
});

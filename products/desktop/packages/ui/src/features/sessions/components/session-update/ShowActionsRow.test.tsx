import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openAgentAction = vi.hoisted(() => vi.fn());
const track = vi.hoisted(() => vi.fn());
const visibility = vi.hoisted(() => ({ current: false }));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));
vi.mock("@posthog/ui/primitives/hooks/useInView", () => ({
  useInView: () => [vi.fn(), visibility.current],
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    deepLink: {
      openAgentAction: {
        mutationOptions: () => ({ mutationFn: openAgentAction }),
      },
    },
  }),
}));

import { SessionTaskIdProvider } from "../../useSessionTaskId";
import { ShowActionsRow } from "./ShowActionsRow";

function card(actions: unknown[], toolCallId = "tc") {
  const toolCall = { toolCallId, rawInput: { actions } } as ToolCall;
  return (
    <QueryClientProvider client={new QueryClient()}>
      <SessionTaskIdProvider taskId="source-task">
        <ShowActionsRow toolCall={toolCall} turnComplete />
      </SessionTaskIdProvider>
    </QueryClientProvider>
  );
}

function renderCard(actions: unknown[], toolCallId?: string) {
  return render(card(actions, toolCallId));
}

describe("ShowActionsRow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    visibility.current = false;
  });

  it("draws a button per usable action and drops one that cannot open anything", () => {
    renderCard([
      { kind: "compose", label: "Fix the bug", prompt: "Fix the login bug" },
      { kind: "open_space", label: "Open the space", channel_id: "chan" },
      // No canvas id, so this one could only ever build a broken link.
      { kind: "open_canvas", label: "Open the canvas", channel_id: "chan" },
    ]);

    expect(screen.getAllByRole("button")).toHaveLength(2);
    expect(screen.getByText("Fix the bug")).toBeTruthy();
    expect(screen.getByText("Open the space")).toBeTruthy();
    expect(screen.queryByText("Open the canvas")).toBeNull();
  });

  it("hands the host a typed action, never a url", async () => {
    renderCard([
      { kind: "open_space", label: "Open the space", channel_id: "chan" },
    ]);

    await userEvent.click(screen.getByText("Open the space"));

    await waitFor(() => expect(openAgentAction).toHaveBeenCalled());
    expect(openAgentAction.mock.calls[0]?.[0]).toEqual({
      action: { kind: "open_space", channel_id: "chan" },
      attribution: {
        action_id: "source-task:tc:0",
        source_task_id: "source-task",
        tool_call_id: "tc",
        action_index: 0,
      },
    });
    expect(track).toHaveBeenCalledWith("Agent action clicked", {
      action_id: "source-task:tc:0",
      source_task_id: "source-task",
      tool_call_id: "tc",
      action_index: 0,
      action_kind: "open_space",
    });
  });

  it("records each visible action once across remounts", () => {
    const actions = [
      { kind: "open_space", label: "Open the space", channel_id: "chan" },
    ];
    const first = renderCard(actions, "tc-visible");

    expect(track).not.toHaveBeenCalledWith(
      "Agent action shown",
      expect.anything(),
    );

    visibility.current = true;
    first.rerender(card(actions, "tc-visible"));

    expect(track).toHaveBeenCalledWith("Agent action shown", {
      action_id: "source-task:tc-visible:0",
      source_task_id: "source-task",
      tool_call_id: "tc-visible",
      action_index: 0,
      action_kind: "open_space",
    });

    first.unmount();
    renderCard(actions, "tc-visible");

    expect(track).toHaveBeenCalledTimes(1);
  });
});

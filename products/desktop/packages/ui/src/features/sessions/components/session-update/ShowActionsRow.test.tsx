import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { SessionTaskIdProvider } from "@posthog/ui/features/sessions/useSessionTaskId";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const openAgentAction = vi.hoisted(() => vi.fn());
const track = vi.hoisted(() => vi.fn());
const getCachedTask = vi.hoisted(() => vi.fn());

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    deepLink: {
      openAgentAction: {
        mutationOptions: (options: object) => ({
          mutationFn: openAgentAction,
          ...options,
        }),
      },
    },
  }),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));

vi.mock("@posthog/ui/features/tasks/queries", () => ({
  getCachedTask,
  getCachedTaskDetail: () => undefined,
}));

import { ShowActionsRow } from "./ShowActionsRow";

function renderCard(actions: unknown[], taskId?: string) {
  const toolCall = { toolCallId: "tc", rawInput: { actions } } as ToolCall;
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SessionTaskIdProvider taskId={taskId}>
        <ShowActionsRow toolCall={toolCall} turnComplete />
      </SessionTaskIdProvider>
    </QueryClientProvider>,
  );
}

describe("ShowActionsRow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
    });
  });

  it("captures the accepted offer with the flow that made it", async () => {
    openAgentAction.mockResolvedValue(true);
    getCachedTask.mockReturnValue({
      id: "task-1",
      origin_key: "desktop_onboarding_session:42",
    });

    renderCard([{ kind: "open_inbox", label: "Open Self-driving" }], "task-1");
    await userEvent.click(screen.getByText("Open Self-driving"));

    await waitFor(() => expect(track).toHaveBeenCalled());
    expect(track).toHaveBeenCalledWith(ANALYTICS_EVENTS.AGENT_ACTION_CLICKED, {
      action_kind: "open_inbox",
      task_id: "task-1",
      task_origin_key: "desktop_onboarding_session:42",
      opened: true,
    });
  });
});

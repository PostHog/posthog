import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const openAgentAction = vi.hoisted(() => vi.fn());

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    deepLink: {
      openAgentAction: {
        mutationOptions: () => ({ mutationFn: openAgentAction }),
      },
    },
  }),
}));

import { ShowActionsRow } from "./ShowActionsRow";

function renderCard(actions: unknown[]) {
  const toolCall = { toolCallId: "tc", rawInput: { actions } } as ToolCall;
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ShowActionsRow toolCall={toolCall} turnComplete />
    </QueryClientProvider>,
  );
}

describe("ShowActionsRow", () => {
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
});

import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
  beforeEach(() => {
    openAgentAction.mockClear();
  });

  it("draws a button per usable action and drops one that cannot open anything", () => {
    renderCard([
      { kind: "compose", label: "Fix the bug", prompt: "Fix the login bug" },
      {
        kind: "compose",
        label: "Add PostHog",
        description: "Instruments the app and opens a task to review it",
        prompt: "/instrument",
      },
      { kind: "open_space", label: "Open the space", channel_id: "chan" },
      // No canvas id, so this one could only ever build a broken link.
      { kind: "open_canvas", label: "Open the canvas", channel_id: "chan" },
    ]);

    expect(screen.getAllByRole("button")).toHaveLength(3);
    expect(screen.getByText("Fix the bug")).toBeTruthy();
    expect(screen.getByText("Add PostHog")).toBeTruthy();
    expect(
      screen.getByText("Instruments the app and opens a task to review it"),
    ).toBeTruthy();
    expect(screen.getByText("Open the space")).toBeTruthy();
    expect(screen.queryByText("Open the canvas")).toBeNull();
  });

  it("keeps the order the agent supplied, even with a pill before a card", () => {
    renderCard([
      { kind: "open_space", label: "Open the space", channel_id: "chan" },
      {
        kind: "compose",
        label: "Add PostHog",
        description: "Instruments the app and opens a task to review it",
        prompt: "/instrument",
      },
      { kind: "open_inbox", label: "Review findings" },
    ]);

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Open the space",
      "Add PostHogInstruments the app and opens a task to review it",
      "Review findings",
    ]);
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

  // A description is presentation, like the label, so the host must never be
  // handed one: it would ride into the url the host builds.
  it("keeps the description off the action it sends the host", async () => {
    renderCard([
      {
        kind: "compose",
        label: "Fix the bug",
        description: "Opens a task that patches the login redirect",
        prompt: "Fix the login bug",
      },
    ]);

    expect(screen.getByText("Fix the bug")).toBeTruthy();
    expect(
      screen.getByText("Opens a task that patches the login redirect"),
    ).toBeTruthy();

    await userEvent.click(screen.getByText("Fix the bug"));

    await waitFor(() => expect(openAgentAction).toHaveBeenCalled());
    expect(openAgentAction.mock.calls[0]?.[0]).toEqual({
      action: { kind: "compose", prompt: "Fix the login bug" },
    });
  });
});

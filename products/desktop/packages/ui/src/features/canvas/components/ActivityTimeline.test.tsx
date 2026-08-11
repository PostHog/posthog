import type { Task } from "@posthog/shared/domain-types";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/git-interaction/usePrDetails", () => ({
  usePrDetails: () => ({
    meta: { state: "open", merged: false, draft: false },
  }),
}));

import { useThreadNavigationStore } from "@posthog/ui/features/sessions/threadNavigationStore";
import { ActivityTimeline } from "./ActivityTimeline";

const task = {
  id: "task-1",
  created_at: "2026-07-17T09:00:00Z",
  updated_at: "2026-07-17T09:00:00Z",
  created_by: { uuid: "u1", first_name: "Shy", last_name: "Alter" },
  latest_run: null,
} as unknown as Task;

const conversationItems = [
  {
    type: "user_message" as const,
    id: "turn-1-1-user",
    content: "first thing\nand more detail",
    timestamp: Date.parse("2026-07-17T09:05:00Z"),
  },
  {
    type: "user_message" as const,
    id: "turn-2-2-user",
    content: "second thing",
    timestamp: Date.parse("2026-07-17T09:10:00Z"),
  },
];

function renderTimeline(canOpenInPlace?: boolean, items = conversationItems) {
  return render(
    <ActivityTimeline
      task={task}
      timeline={[]}
      // biome-ignore lint/suspicious/noExplicitAny: narrow fixture for the rows under test
      conversationItems={items as any}
      isTaskAuthor
      canForward={false}
      canOpenInPlace={canOpenInPlace}
      onSendToAgent={() => {}}
      onDelete={() => {}}
    />,
  );
}

beforeEach(() => {
  useThreadNavigationStore.setState({ scrollRequests: {} });
});

describe("ActivityTimeline", () => {
  it("renders each message preview with a chat navigation action", () => {
    renderTimeline(true);

    expect(screen.getByText(/first thing/)).toBeInTheDocument();
    expect(screen.getByText(/second thing/)).toBeInTheDocument();
    const actions = screen.getAllByRole("button", { name: "View in chat" });
    expect(actions).toHaveLength(2);
    for (const action of actions) {
      expect(action).toHaveAttribute("data-size", "icon-xs");
      expect(action.closest('[role="toolbar"]')).toBeNull();
    }
  });

  it("truncates long message previews to 100 characters", () => {
    const content = `${"a".repeat(100)}overflow`;
    renderTimeline(true, [
      {
        type: "user_message",
        id: "long-message",
        content,
        timestamp: Date.parse("2026-07-17T09:05:00Z"),
      },
    ]);

    expect(screen.getByText(`${"a".repeat(100)}…`)).toBeInTheDocument();
    expect(screen.queryByText(content)).toBeNull();
  });

  it("asks the transcript to scroll to the selected message", () => {
    renderTimeline(true);

    fireEvent.click(screen.getAllByRole("button", { name: "View in chat" })[1]);

    expect(useThreadNavigationStore.getState().scrollRequests["task-1"]).toBe(
      "turn-2-2-user",
    );
  });

  it("hides chat navigation when no transcript is alongside", () => {
    renderTimeline();

    expect(screen.queryByRole("button", { name: "View in chat" })).toBeNull();
  });

  it("keeps long structured references intact in conversation previews", () => {
    renderTimeline(false, [
      {
        type: "user_message",
        id: "pr-message",
        content: `<github_pr number="73874" title="Loading…" url="https://github.com/PostHog/posthog/pull/73874/files?diff=split&long=${"a".repeat(80)}" /> ${"b".repeat(100)}`,
        timestamp: Date.parse("2026-07-17T09:05:00Z"),
      },
    ]);

    expect(screen.getByText("#73874 - Loading…")).toBeInTheDocument();
    expect(screen.queryByText(/<github_pr/)).toBeNull();
    expect(screen.getByText(/^b+…$/)).toBeInTheDocument();
  });

  it("folds injected channel context by default", () => {
    renderTimeline(true, [
      {
        type: "user_message",
        id: "context-message",
        content:
          'Review this\n\n<channel_context channel="code">Saved workspace context</channel_context>',
        timestamp: Date.parse("2026-07-17T09:05:00Z"),
      },
    ]);

    expect(screen.getByText("Review this")).toBeInTheDocument();
    expect(screen.queryByText(/<channel_context/)).toBeNull();
    expect(screen.queryByText("Saved workspace context")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "#code CONTEXT.md" }));

    expect(screen.getByText("Saved workspace context")).toBeVisible();
    expect(useThreadNavigationStore.getState().scrollRequests).toEqual({});
  });

  it("hides injected custom instructions from conversation previews", () => {
    renderTimeline(true, [
      {
        type: "user_message",
        id: "custom-instructions-message",
        content:
          "Review this PR\n\n<user_custom_instructions>\nThe user has saved custom instructions that apply to all of their tasks. Follow them.\n\nNever update an existing PR description.\n</user_custom_instructions>",
        timestamp: Date.parse("2026-07-17T09:05:00Z"),
      },
    ]);

    expect(screen.getByText("Review this PR")).toBeInTheDocument();
    expect(screen.queryByText(/user_custom_instructions/)).toBeNull();
    expect(
      screen.queryByText("Never update an existing PR description."),
    ).toBeNull();
  });

  it("shows user-authored custom-instruction tag examples", () => {
    renderTimeline(true, [
      {
        type: "user_message",
        id: "literal-custom-instructions-message",
        content:
          "Render this example: <user_custom_instructions>be terse</user_custom_instructions>",
        timestamp: Date.parse("2026-07-17T09:05:00Z"),
      },
    ]);

    expect(screen.getByText(/user_custom_instructions/)).toBeInTheDocument();
    expect(screen.getByText(/be terse/)).toBeInTheDocument();
  });
});

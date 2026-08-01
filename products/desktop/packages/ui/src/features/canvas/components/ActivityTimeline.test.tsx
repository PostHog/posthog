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

// Every conversation row is attributed to the task's creator, which is exactly why
// an author-derived accessible name would be identical on all of them.
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
  it("names each message row by its own content, not a shared template", () => {
    renderTimeline(true);

    expect(screen.getAllByRole("button")).toHaveLength(2);
    // `name` here is the computed accessible name, so this is what a screen reader
    // announces: each row carries the content a sighted user sees, which is what
    // makes the two distinguishable — the author is the same on every row.
    expect(
      screen.getByRole("button", { name: /Shy Alter.*first thing/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Shy Alter.*second thing/ }),
    ).toBeInTheDocument();
    // The avatar is decorative, so its initials stay out of the name.
    expect(screen.queryByRole("button", { name: /SA/ })).toBeNull();
  });

  it("asks the transcript to scroll to the clicked message", () => {
    renderTimeline(true);

    fireEvent.click(screen.getAllByRole("button")[1]);

    expect(useThreadNavigationStore.getState().scrollRequests["task-1"]).toBe(
      "turn-2-2-user",
    );
  });

  it("leaves rows inert with no transcript alongside to drive", () => {
    renderTimeline();

    expect(screen.queryAllByRole("button")).toHaveLength(0);
    const body = screen.getByText(/first thing/).closest("[data-slot]");
    expect(body).toHaveClass("whitespace-pre-wrap", "break-words");
    expect(body).not.toHaveClass("line-clamp-1");
  });

  it("renders structured references natively in conversation previews", () => {
    renderTimeline(false, [
      {
        type: "user_message",
        id: "pr-message",
        content:
          '<github_pr number="73874" title="Loading…" url="https://github.com/PostHog/posthog/pull/73874" />',
        timestamp: Date.parse("2026-07-17T09:05:00Z"),
      },
    ]);

    expect(screen.getByText("#73874 - Loading…")).toBeInTheDocument();
    expect(screen.queryByText(/<github_pr/)).toBeNull();
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
});

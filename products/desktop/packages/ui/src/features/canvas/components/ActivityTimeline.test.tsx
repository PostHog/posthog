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

describe("ActivityTimeline events and comments", () => {
  const threadMessage = (
    id: string,
    event: string,
    payload: Record<string, unknown>,
  ) => ({
    kind: "human" as const,
    timestamp: Date.parse("2026-07-17T09:20:00Z"),
    message: {
      id,
      task: "task-1",
      content: "",
      created_at: "2026-07-17T09:20:00Z",
      author_kind: "agent" as const,
      event,
      payload,
    },
  });

  const commentThread = (overrides = {}) => ({
    id: "thread-1",
    target: { id: "artifact-1", type: "artifact", name: "report.md" },
    content: "this needs a guard",
    content_truncated: false,
    selected_text: "every event should also go to the activity panel",
    author: { id: 7, uuid: "u2", first_name: "Ben", last_name: "White" },
    created_at: "2026-07-17T09:30:00Z",
    last_activity_at: "2026-07-17T09:35:00Z",
    reply_count: 2,
    participants: [
      { id: 7, uuid: "u2", first_name: "Ben", last_name: "White" },
      { id: 9, uuid: "u3", first_name: "Shy", last_name: "Alter" },
    ],
    mentioned_user_ids: [],
    resolved: false,
    state_event: null,
    latest_reply: null,
    ...overrides,
  });

  function renderRows(props: Record<string, unknown>) {
    return render(
      <ActivityTimeline
        task={task}
        timeline={[]}
        conversationItems={[]}
        isTaskAuthor
        canForward={false}
        onSendToAgent={() => {}}
        onDelete={() => {}}
        // biome-ignore lint/suspicious/noExplicitAny: narrow fixture for the rows under test
        {...(props as any)}
      />,
    );
  }

  it("writes the reason on a failed run, so nobody has to open the transcript", () => {
    renderRows({
      timeline: [
        threadMessage("m1", "run_failed", {
          run_id: "run-1",
          error_summary: "Command failed: pnpm build",
        }),
      ],
    });

    expect(screen.getByText(/Command failed: pnpm build/)).toBeInTheDocument();
  });

  it("labels the run only once a task has run more than once", () => {
    const message = threadMessage("m1", "run_started", {
      run_id: "run-1",
      environment: "cloud",
      branch: "shy/activity",
      run_number: 2,
    });

    const single = renderRows({ timeline: [message], runCount: 1 });
    expect(screen.getByText(/Agent started work/)).toBeInTheDocument();
    single.unmount();

    renderRows({ timeline: [message], runCount: 2 });
    expect(screen.getByText(/Agent started run 2/)).toBeInTheDocument();
  });

  it("keeps the anchor with the comment it points at", () => {
    renderRows({ commentThreads: [commentThread()], commentsEnabled: true });

    expect(
      screen.getByText(/every event should also go to the activity panel/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("2 replies · Ben White, Shy Alter"),
    ).toBeInTheDocument();
  });

  it("reads as a mention when the mention is of you", () => {
    renderRows({
      commentThreads: [commentThread({ mentioned_user_ids: [42] })],
      commentsEnabled: true,
      currentUserId: 42,
    });

    expect(screen.getByText("mentioned you on")).toBeInTheDocument();
  });

  it("reads as an ordinary comment when someone else was mentioned", () => {
    renderRows({
      commentThreads: [commentThread({ mentioned_user_ids: [7] })],
      commentsEnabled: true,
      currentUserId: 42,
    });

    expect(screen.getByText("commented on")).toBeInTheDocument();
  });

  it("gives resolve its own row, with who resolved it", () => {
    renderRows({
      commentThreads: [
        commentThread({
          resolved: true,
          state_event: {
            state: "resolved",
            created_at: "2026-07-17T09:40:00Z",
            author: {
              id: 9,
              uuid: "u3",
              first_name: "Shy",
              last_name: "Alter",
            },
          },
        }),
      ],
      commentsEnabled: true,
    });

    expect(screen.getByText("resolved a thread on")).toBeInTheDocument();
  });

  it("shows no comment rows when comments are off", () => {
    renderRows({ commentThreads: [commentThread()], commentsEnabled: false });

    expect(screen.queryByText("commented on")).toBeNull();
  });
});

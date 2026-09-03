import { buildThreadTimeline } from "@posthog/core/canvas/threadTimeline";
import type { Task, TaskThreadMessage } from "@posthog/shared/domain-types";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/git-interaction/usePrDetails", () => ({
  usePrDetails: () => ({
    meta: { state: "open", merged: false, draft: false },
  }),
}));

import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
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

function renderTimeline(
  canOpenInPlace?: boolean,
  items: ConversationItem[] = conversationItems,
) {
  return render(
    <ActivityTimeline
      task={task}
      timeline={[]}
      messages={[]}
      // biome-ignore lint/suspicious/noExplicitAny: narrow fixture for the rows under test
      conversationItems={items as any}
      canOpenInPlace={canOpenInPlace}
    />,
  );
}

beforeEach(() => {
  useThreadNavigationStore.setState({ scrollRequests: {}, listeners: {} });
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

  it("opens a message to its full text", () => {
    renderTimeline(true);

    fireEvent.click(screen.getByRole("button", { name: /first thing/ }));

    expect(screen.getByText(/and more detail/)).toBeInTheDocument();
  });

  it("places a delayed initial placeholder at task creation", () => {
    renderTimeline(false, [
      {
        type: "user_message",
        id: "initial-optimistic",
        content: "initial request",
        timestamp: Date.parse("2026-07-17T12:00:00Z"),
        pinToTop: true,
      },
      {
        type: "user_message",
        id: "later-message",
        content: "later follow-up",
        timestamp: Date.parse("2026-07-17T10:00:00Z"),
      },
    ]);

    expect(
      screen.getAllByRole("button").map((button) => button.textContent),
    ).toEqual([
      expect.stringContaining("initial request"),
      expect.stringContaining("later follow-up"),
    ]);
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

    // The whole message fits on the row, so the preview is the content, rendered not raw.
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
    // The context lives inside the row, so open it before reaching for the fold.
    fireEvent.click(screen.getByRole("button", { name: /Review this/ }));

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
    createdAt = "2026-07-17T09:20:00Z",
  ) => ({
    id,
    task: "task-1",
    content: "",
    created_at: createdAt,
    author_kind: "agent" as const,
    event,
    payload,
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

  // `timeline` is derived the way the panel derives it, so a fixture can't hand the
  // component a row shape `buildThreadTimeline` would never emit. Event rows only render
  // if they survive that filter on their way in.
  function renderRows({
    messages = [],
    ...props
  }: Record<string, unknown> & { messages?: TaskThreadMessage[] }) {
    return render(
      <ActivityTimeline
        task={task}
        timeline={buildThreadTimeline(messages)}
        messages={messages}
        conversationItems={[]}
        // biome-ignore lint/suspicious/noExplicitAny: narrow fixture for the rows under test
        {...(props as any)}
      />,
    );
  }

  it("keeps the failure reason one click away, not on the row", () => {
    // Rows are collapsed so the panel reads as a timeline; the detail is what opening is for.
    renderRows({
      messages: [
        threadMessage("m1", "run_failed", {
          run_id: "run-1",
          error_summary: "Command failed: pnpm build",
        }),
      ],
    });

    expect(screen.queryByText(/Command failed: pnpm build/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Run failed/ }));

    expect(screen.getByText(/Command failed: pnpm build/)).toBeInTheDocument();
  });

  it("numbers a run only once the feed shows more than one", () => {
    const first = threadMessage("m1", "run_started", {
      run_id: "run-1",
      environment: "cloud",
      branch: "shy/activity",
    });
    const second = threadMessage("m2", "run_started", { run_id: "run-2" });

    const single = renderRows({ messages: [first] });
    expect(screen.getByText(/Agent started work/)).toBeInTheDocument();
    single.unmount();

    renderRows({ messages: [first, second] });
    expect(screen.getByText(/Agent started run 2/)).toBeInTheDocument();
  });

  it("keeps the anchor with the comment it points at, once opened", () => {
    renderRows({ commentThreads: [commentThread()] });

    expect(
      screen.queryByText(/every event should also go to the activity panel/),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /commented on/ }));

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
      currentUserId: 42,
    });

    expect(screen.getByText("mentioned you on")).toBeInTheDocument();
  });

  it("reads as an ordinary comment when someone else was mentioned", () => {
    renderRows({
      commentThreads: [commentThread({ mentioned_user_ids: [7] })],
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
    });

    expect(screen.getByText("resolved a thread on")).toBeInTheDocument();
  });

  it("collapses a stretch of pushes to one branch into one row", () => {
    renderRows({
      messages: [1, 2, 3].map((index) =>
        threadMessage(
          `m${index}`,
          "commits_pushed",
          {
            run_id: "run-1",
            branch: "shy/activity",
            repository: "PostHog/posthog",
            commits: [{ sha: `sha${index}`, subject: `work ${index}` }],
            total: 1,
          },
          `2026-07-17T09:2${index}:00Z`,
        ),
      ),
    });

    expect(screen.getByText(/3 commits pushed/)).toBeInTheDocument();
    expect(screen.queryByText(/1 commit pushed/)).toBeNull();
    expect(screen.getByText(/to shy\/activity/)).toBeInTheDocument();
  });

  it("tells grouped pull requests apart by number, not by url", () => {
    // Every row said "Pull request opened · https://github.com/…", which truncates to the
    // same string, so four different pull requests read as one repeated four times.
    renderRows({
      messages: [11, 12].map((number) =>
        threadMessage(`m${number}`, "pr_created", {
          pr_url: `https://github.com/PostHog/posthog/pull/${number}`,
        }),
      ),
    });

    fireEvent.click(
      screen.getByRole("button", { name: /2 pull requests opened/ }),
    );

    expect(screen.getByText("PostHog/posthog#11")).toBeInTheDocument();
    expect(screen.getByText("PostHog/posthog#12")).toBeInTheDocument();
  });
});

describe("ActivityTimeline chat jump", () => {
  it("takes the transcript to the row's own message", () => {
    useThreadNavigationStore.getState().registerTranscript("task-1");
    renderTimeline(true);

    fireEvent.click(screen.getByRole("button", { name: /second thing/ }));
    const row = screen
      .getByRole("button", { name: /second thing/ })
      .closest(".group") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Show in chat" }));

    expect(useThreadNavigationStore.getState().scrollRequests["task-1"]).toBe(
      "turn-2-2-user",
    );
  });

  it("offers no jump on a row the transcript does not hold", () => {
    // Only a prompt is the same item in both panes. A thread reply has no counterpart to
    // scroll to, and the prompt of the surrounding turn is not what the reader clicked, so
    // the row opens to its text and offers nothing further.
    useThreadNavigationStore.getState().registerTranscript("task-1");
    const reply = {
      id: "reply-1",
      task: "task-1",
      author: { id: 7, uuid: "u2", first_name: "Ben", last_name: "White" },
      author_kind: "human" as const,
      content: "you seeing this?",
      created_at: "2026-07-17T09:30:00Z",
    };
    render(
      <ActivityTimeline
        task={task}
        // biome-ignore lint/suspicious/noExplicitAny: narrow fixture for the row under test
        timeline={buildThreadTimeline([reply] as any)}
        // biome-ignore lint/suspicious/noExplicitAny: narrow fixture for the row under test
        messages={[reply] as any}
        // biome-ignore lint/suspicious/noExplicitAny: narrow fixture for the row under test
        conversationItems={conversationItems as any}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /you seeing this/ }));

    expect(screen.queryByRole("button", { name: "Show in chat" })).toBeNull();
  });

  it("offers no jump when the chat holds no prompt to land on", () => {
    // Nothing in the transcript can be scrolled to, so the row stays inert rather than
    // growing a button that goes nowhere.
    useThreadNavigationStore.getState().registerTranscript("task-1");
    renderTimeline(true, []);

    expect(
      screen.queryByRole("button", { name: /created this task/ }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Show in chat" })).toBeNull();
  });

  it("offers no jump when no transcript is mounted to answer it", () => {
    renderTimeline(true);

    fireEvent.click(screen.getByRole("button", { name: /second thing/ }));

    expect(screen.queryByRole("button", { name: "Show in chat" })).toBeNull();
  });
});

describe("ActivityTimeline connectors", () => {
  it("runs the line between every pair of beads, and no further", () => {
    // Each row draws the half above and the half below its own bead, so consecutive rows
    // meet: the first row has no upper half and the last has no lower one.
    const { container } = renderTimeline(true);

    const rows = [...container.querySelectorAll(".group")];
    const halves = rows.map(
      (row) => row.querySelectorAll("[aria-hidden].w-px").length,
    );
    expect(rows.length).toBeGreaterThan(2);
    expect(halves.at(0)).toBe(1);
    expect(halves.at(-1)).toBe(1);
    expect(halves.slice(1, -1).every((count) => count === 2)).toBe(true);
  });

  it("always opens a message to its full text", () => {
    renderTimeline(true);

    fireEvent.click(screen.getByRole("button", { name: /second thing/ }));

    expect(screen.getAllByText(/second thing/).length).toBeGreaterThan(1);
  });
});

describe("ActivityTimeline thread replies", () => {
  const reply = {
    id: "reply-1",
    task: "task-1",
    author: { id: 7, uuid: "u2", first_name: "Ben", last_name: "White" },
    author_kind: "human" as const,
    content: "@[Shy Alter](shy@example.com) you seeing this?\nsecond line",
    created_at: "2026-07-17T09:30:00Z",
  };

  it("collapses a legacy thread reply like every other row", () => {
    // Legacy replies collapse like every other row, so the panel reads as a timeline
    // rather than a chat log.
    render(
      <ActivityTimeline
        task={task}
        // biome-ignore lint/suspicious/noExplicitAny: narrow fixture for the row under test
        timeline={buildThreadTimeline([reply] as any)}
        // biome-ignore lint/suspicious/noExplicitAny: narrow fixture for the row under test
        messages={[reply] as any}
        conversationItems={[]}
      />,
    );

    expect(screen.queryByText(/second line/)).toBeNull();
    // The mention renders as a chip in the preview, not as its markup.
    expect(screen.queryByText(/@\[/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /you seeing this/ }));

    expect(screen.getByText(/second line/)).toBeInTheDocument();
  });
});

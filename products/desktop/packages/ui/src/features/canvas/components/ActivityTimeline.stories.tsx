import { buildThreadTimeline } from "@posthog/core/canvas/threadTimeline";
import type {
  Task,
  TaskCommentThreadSummary,
  TaskThreadMessage,
} from "@posthog/shared/domain-types";
import { ActivityTimeline } from "@posthog/ui/features/canvas/components/ActivityTimeline";
import {
  CommitFilesList,
  DetailBlock,
} from "@posthog/ui/features/canvas/components/activityRows";
import type { Meta, StoryObj } from "@storybook/react-vite";

const shy = {
  id: 9,
  uuid: "u-shy",
  first_name: "Shy",
  last_name: "Alter",
  email: "shy@example.com",
};
const ben = {
  id: 7,
  uuid: "u-ben",
  first_name: "Ben",
  last_name: "White",
  email: "ben@example.com",
};

const task = {
  id: "task-1",
  created_at: "2026-08-04T09:00:00Z",
  updated_at: "2026-08-05T16:00:00Z",
  created_by: shy,
  latest_run: { id: "run-1", status: "completed" },
} as unknown as Task;

function event(
  id: string,
  event: string,
  payload: Record<string, unknown>,
  createdAt: string,
): TaskThreadMessage {
  return {
    id,
    task: task.id,
    content: "",
    created_at: createdAt,
    author_kind: "agent",
    event,
    payload,
  } as TaskThreadMessage;
}

// The raw thread, as the API returns it. `timeline` is derived the way the panel derives
// it, so a story cannot show a row shape production never produces.
const messages: TaskThreadMessage[] = [
  event(
    "e1",
    "run_started",
    { run_id: "run-1", environment: "cloud", branch: "shy/activity-events" },
    "2026-08-04T09:02:00Z",
  ),
  event("e2", "awaiting_input", { run_id: "run-1" }, "2026-08-04T09:40:00Z"),
  event(
    "e3",
    "artifact_created",
    {
      artifact_id: "artifact-1",
      name: "activity-events.html",
      artifact_type: "document",
      version: 1,
    },
    "2026-08-04T10:10:00Z",
  ),
  event(
    "e4",
    "message_forwarded",
    { message_id: "m-1", run_id: "run-1" },
    "2026-08-05T09:30:00Z",
  ),
  event(
    "e5",
    "artifact_revised",
    {
      artifact_id: "artifact-1",
      name: "activity-events.html",
      artifact_type: "document",
      version: 2,
    },
    "2026-08-05T10:00:00Z",
  ),
  event(
    "e6",
    "commits_pushed",
    {
      run_id: "run-1",
      branch: "shy/activity-events",
      repository: "PostHog/posthog",
      total: 2,
      head_sha: "9c2f1aa",
      commits: [
        {
          sha: "5a0a28b",
          subject: "feat(desktop): draw activity events on the timeline",
          url: "https://github.com/PostHog/posthog/commit/5a0a28b",
        },
        {
          sha: "9c2f1aa",
          subject: "fix(desktop): keep the timeline scroll anchored",
          url: "https://github.com/PostHog/posthog/commit/9c2f1aa",
        },
      ],
    },
    "2026-08-05T14:45:00Z",
  ),
  {
    ...event(
      "e6b",
      "comment_added",
      {
        comment_id: "c-1",
        root_comment_id: "c-1",
        scope: "task_artifact",
        item_id: "artifact-1",
      },
      "2026-08-05T15:00:00Z",
    ),
    author_kind: "human",
    author: shy,
  } as TaskThreadMessage,
  event(
    "e6c",
    "artifact_revised",
    {
      artifact_id: "artifact-1",
      name: "activity-events.html",
      artifact_type: "document",
      version: 3,
    },
    "2026-08-05T15:10:00Z",
  ),
  event(
    "e7",
    "pr_merged",
    {
      pr_url: "https://github.com/PostHog/posthog/pull/80060",
      repository: "PostHog/posthog",
      pr_number: 80060,
      actor: "benjackwhite",
    },
    "2026-08-05T15:30:00Z",
  ),
];

const timeline = buildThreadTimeline(messages);

const BUSY_BRANCHES = ["shy/reports-panel", "shy/drop-report-tables"];

// One run's worth of noise: a push at a time, with the pull requests they opened between.
const busyMessages: TaskThreadMessage[] = [
  event(
    "b0",
    "run_started",
    { run_id: "run-2", environment: "cloud", branch: BUSY_BRANCHES[0] },
    "2026-08-05T09:00:00Z",
  ),
  ...Array.from({ length: 9 }, (_, index) =>
    event(
      `b${index + 1}`,
      "commits_pushed",
      {
        run_id: "run-2",
        branch: BUSY_BRANCHES[index % 2],
        repository: "PostHog/posthog",
        total: 1,
        commits: [
          {
            sha: `${index + 1}c0ffee`,
            subject: `chore(desktop): iterate ${index + 1}`,
            url: `https://github.com/PostHog/posthog/commit/${index + 1}c0ffee`,
          },
        ],
      },
      `2026-08-05T${10 + Math.floor(index / 3)}:${String((index % 3) * 15 + 5).padStart(2, "0")}:00Z`,
    ),
  ),
  ...[80061, 80062, 80063].map((number, index) =>
    event(
      `bp${number}`,
      "pr_created",
      { pr_url: `https://github.com/PostHog/posthog/pull/${number}` },
      `2026-08-05T13:${index * 10 + 10}:00Z`,
    ),
  ),
];

const commentThreads: TaskCommentThreadSummary[] = [
  {
    id: "thread-1",
    target: {
      id: "artifact-1",
      type: "artifact",
      name: "activity-events.html",
    },
    content:
      "Missing the awaiting-input case — that's the one that costs us time.",
    content_truncated: false,
    selected_text: "every event should also go to the activity panel",
    author: shy,
    created_at: "2026-08-05T08:00:00Z",
    last_activity_at: "2026-08-05T08:45:00Z",
    reply_count: 3,
    participants: [shy, ben],
    mentioned_user_ids: [],
    resolved: false,
    state_event: null,
    latest_reply: {
      author: ben,
      content: "collapse looks right, keep resolve separate",
      created_at: "2026-08-05T08:45:00Z",
    },
  },
  {
    id: "thread-2",
    target: { id: "canvas-1", type: "canvas", name: "Activity mockup" },
    content:
      "@[Ben White](ben@example.com) can you sanity check the collapse rule before this ships?",
    content_truncated: false,
    selected_text: null,
    author: shy,
    created_at: "2026-08-05T09:00:00Z",
    last_activity_at: "2026-08-05T09:00:00Z",
    reply_count: 0,
    participants: [shy],
    mentioned_user_ids: [ben.id],
    resolved: true,
    state_event: {
      state: "resolved",
      author: ben,
      created_at: "2026-08-05T11:00:00Z",
    },
    latest_reply: null,
  },
];

const meta: Meta<typeof ActivityTimeline> = {
  title: "Canvas/ActivityTimeline",
  component: ActivityTimeline,
  parameters: { layout: "centered" },
  decorators: [
    (Story) => (
      <div className="w-[468px] border border-border bg-gray-1">
        <Story />
      </div>
    ),
  ],
};

export default meta;

type Story = StoryObj<typeof ActivityTimeline>;

/** Every row the timeline can draw, in the order a real task produces them. */
export const FullTimeline: Story = {
  args: {
    task,
    timeline,
    messages,
    conversationItems: [
      {
        type: "user_message",
        id: "turn-1",
        content: "Add the events that belong on the activity panel.",
        timestamp: Date.parse("2026-08-04T09:05:00Z"),
      },
      // biome-ignore lint/suspicious/noExplicitAny: story fixture for the row under test
    ] as any,
    commentThreads,
    currentUserId: ben.id,
  },
};

/** What a stack of branches looks like: nine pushes and three pull requests, which the
 *  panel collapses into one row per branch and one row for the pull requests. */
export const GroupedRun: Story = {
  args: {
    task,
    timeline: buildThreadTimeline(busyMessages),
    messages: busyMessages,
    conversationItems: [],
  },
};

/** The changed-file list a commit row shows once GitHub answers. In the timeline
 *  above the fetch never resolves (no workspace-server in Storybook), so the
 *  presentational list is shown on its own here. */
export const CommitFiles: StoryObj = {
  render: () => (
    <div className="p-3">
      <DetailBlock>
        <CommitFilesList
          files={[
            {
              path: "products/desktop/packages/core/src/canvas/activityEvents.ts",
              status: "added",
              linesAdded: 210,
              linesRemoved: 0,
            },
            {
              path: "products/desktop/packages/ui/src/features/canvas/components/activityRows.tsx",
              status: "modified",
              linesAdded: 96,
              linesRemoved: 30,
            },
            {
              path: "products/desktop/packages/core/src/canvas/rows/ActivityBead.tsx",
              status: "renamed",
              originalPath:
                "products/desktop/packages/ui/src/features/canvas/Bead.tsx",
              linesAdded: 4,
              linesRemoved: 4,
            },
            {
              path: "products/desktop/packages/core/src/canvas/activityFlags.ts",
              status: "deleted",
              linesAdded: 0,
              linesRemoved: 41,
            },
          ]}
        />
      </DetailBlock>
    </div>
  ),
};

import { buildThreadTimeline } from "@posthog/core/canvas/threadTimeline";
import type {
  Task,
  TaskCommentThreadSummary,
  TaskThreadMessage,
} from "@posthog/shared/domain-types";
import { ActivityTimeline } from "@posthog/ui/features/canvas/components/ActivityTimeline";
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

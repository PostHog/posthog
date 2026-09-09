import type { ChannelItemModel } from "@posthog/core/canvas/channelItems";
import { Card } from "@posthog/quill";
import type { Task, TaskRun } from "@posthog/shared/domain-types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ChannelItemPreview } from "./ChannelItemPreview";
import type { TaskRowMenuProps } from "./TaskRowMenu";

/**
 * The card as the list shows it — the popup itself carries no styling of its
 * own, so the story supplies the same quill `Card` the shared preview card
 * renders it into.
 */
function CardFrame({
  item,
  menu,
}: {
  item: ChannelItemModel;
  menu: TaskRowMenuProps;
}) {
  return (
    <div className="p-4">
      <Card
        size="sm"
        className="w-72 gap-0 border border-border py-0 shadow-md"
      >
        <ChannelItemPreview
          payload={{ item, menu }}
          onAction={() => {}}
          onSubmenuOpenChange={() => {}}
        />
      </Card>
    </div>
  );
}

function run(overrides: Partial<TaskRun>): TaskRun {
  return {
    id: "run-1",
    task: "task-1",
    team: 1,
    branch: "posthog/importer-cleanup",
    environment: "cloud",
    status: "completed",
    log_url: "",
    error_message: null,
    output: null,
    state: {},
    created_at: "2026-07-16T12:00:00.000Z",
    updated_at: "2026-07-17T12:00:00.000Z",
    completed_at: "2026-07-17T12:00:00.000Z",
    ...overrides,
  };
}

function task(latestRun: TaskRun, overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    task_number: 41,
    slug: "clean-up-the-importer",
    title: "Clean up the importer",
    description: "",
    created_at: "2026-07-16T12:00:00.000Z",
    updated_at: "2026-07-17T12:00:00.000Z",
    origin_product: "user_created",
    repository: "PostHog/code",
    latest_run: latestRun,
    ...overrides,
  };
}

function item(
  latestRun: TaskRun,
  overrides: Partial<ChannelItemModel> = {},
  taskOverrides: Partial<Task> = {},
): ChannelItemModel {
  return {
    key: "task:task-1",
    kind: "task",
    id: "task-1",
    title: "Clean up the importer",
    ts: Date.parse("2026-07-17T12:00:00.000Z"),
    createdAt: Date.parse("2026-07-16T12:00:00.000Z"),
    pinned: false,
    rawStatus: latestRun.status,
    environment: "cloud",
    source: null,
    needsInput: false,
    unread: false,
    authorUser: {
      id: 1,
      uuid: "user-uuid",
      first_name: "Ada",
      last_name: "Lovelace",
      email: "ada@example.com",
    },
    authorName: null,
    authorUuid: "user-uuid",
    templateId: null,
    repository: { key: "posthog/code", label: "PostHog/code" },
    branch: "posthog/importer-cleanup",
    task: task(latestRun, taskOverrides),
    ...overrides,
  };
}

const menu: TaskRowMenuProps = {
  kind: "task",
  id: "task-1",
  title: "Clean up the importer",
  isPinned: false,
  channelId: "channel-1",
  onRename: () => {},
  onAddToCommandCenter: () => {},
  onTogglePin: () => {},
  onArchive: () => {},
};

const meta = {
  title: "Canvas/ChannelItemPreview",
  component: CardFrame,
  args: { menu },
} satisfies Meta<typeof CardFrame>;

export default meta;
type Story = StoryObj<typeof meta>;

/** A finished run: the quiet dot, what the agent signed off with, and its PR. */
export const Finished: Story = {
  args: {
    item: item(
      run({
        output: {
          final_message:
            "Dropped the retry loop, moved the backfill behind a flag, and opened a PR. The importer now fails closed on a bad row instead of skipping it.",
          pr_url: "https://github.com/posthog/posthog/pull/1",
        },
      }),
    ),
  },
};

/** A sandbox coming up: the dot spins and there is nothing said yet. */
export const Starting: Story = {
  args: { item: item(run({ status: "queued", output: null })) },
};

/**
 * The widest the card gets: a title that wraps, a full message, and both an
 * origin and a PR badge, each pointing somewhere. Every line still has to start
 * in the title's column.
 */
export const Crowded: Story = {
  args: {
    item: item(
      run({
        output: {
          // Written to exercise the card, not transcribed from anywhere: long
          // enough to clamp at three lines, and carrying a url whose unbroken
          // width is what used to push the text column out of the card.
          final_message:
            "Swapped the retry loop for a bounded backoff, so the importer now fails closed on a bad row instead of skipping it. The remaining cleanup is tracked in https://github.com/PostHog/posthog/pull/12345 for a follow-up.",
          pr_url: "https://github.com/posthog/posthog/pull/1",
        },
        state: {
          slack_thread_url: "https://example.slack.com/archives/C1/p1",
        },
      }),
      { title: "Clean up the importer's retry handling" },
      { origin_product: "slack" },
    ),
  },
};

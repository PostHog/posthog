import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import { Autocomplete, AutocompleteList, cn, MenuLabel } from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { ActivityRow } from "@posthog/ui/features/canvas/components/ActivityRow";
import { InboxActivityOverflowRow } from "@posthog/ui/features/canvas/components/InboxActivityOverflowRow";
import { InboxActivityRow } from "@posthog/ui/features/canvas/components/InboxActivityRow";
import type { TaskRowMenuProps } from "@posthog/ui/features/canvas/components/TaskRowMenu";
import { inboxStoryReport } from "@posthog/ui/features/inbox/components/inboxStoryFixtures";
import { RAIL_CONTAINER_CLASS } from "@posthog/ui/features/sidebar/components/RailListItem";
import { CHANNELS_SIDEBAR_MIN_WIDTH } from "@posthog/ui/features/sidebar/constants";
import type { Meta, StoryObj } from "@storybook/react-vite";

const ME: UserBasic = {
  id: 1,
  uuid: "me",
  email: "me@example.com",
  first_name: "Sam",
};

const PETER: UserBasic = {
  id: 2,
  uuid: "peter",
  email: "peter@example.com",
  first_name: "Peter",
};

function activity(overrides: Partial<TaskActivityItem>): TaskActivityItem {
  return {
    id: "activity",
    taskId: "task",
    taskTitle: "Untitled task",
    channelId: "channel-1",
    channelName: "growth",
    activityAt: new Date(Date.now() - 20 * 60_000).toISOString(),
    activityKind: "message",
    snippet: "",
    author: null,
    messageId: null,
    isUnread: false,
    ...overrides,
  };
}

const sessions: TaskActivityItem[] = [
  activity({
    id: "a1",
    taskId: "t1",
    taskTitle: "Fix the retention chart tooltip overflow",
    activityKind: "completed",
    snippet:
      "Done. The tooltip now clamps to the chart bounds and the two regression tests pass. I opened a PR with the change and a short note on the root cause.",
    isUnread: true,
  }),
  activity({
    id: "a2",
    taskId: "t2",
    taskTitle: "Investigate slow cohort recalculation",
    activityKind: "awaiting_input",
    snippet:
      "Two approaches fit here. Should I coalesce pending work by cohort, or cap concurrent calculations per team?",
    activityAt: new Date(Date.now() - 2 * 3_600_000).toISOString(),
  }),
  activity({
    id: "a3",
    taskId: "t3",
    taskTitle: "Add buffer health to the replay player",
    author: PETER,
    snippet: "Looks good, can you also cover the paused state?",
    activityAt: new Date(Date.now() - 5 * 3_600_000).toISOString(),
  }),
  activity({
    id: "a4",
    taskId: "t4",
    taskTitle: "Dedupe flag evaluations after reconnect",
    author: ME,
    snippet: "Please retry with the websocket mock instead of the real client.",
    channelName: null,
    channelId: null,
    activityAt: new Date(Date.now() - 26 * 3_600_000).toISOString(),
  }),
  activity({
    id: "a5",
    taskId: "t5",
    taskTitle: "Write the onboarding checklist copy",
    activityKind: "created",
    activityAt: new Date(Date.now() - 30 * 3_600_000).toISOString(),
  }),
];

const reports = [
  inboxStoryReport({
    id: "r1",
    title: "fix(webhooks): retry delivery after a transient timeout",
    priority: "P1",
    implementation_pr_url: "https://github.com/PostHog/posthog/pull/12345",
    implementation_pr_state: "draft",
  }),
  inboxStoryReport({
    id: "r2",
    title: "feat(insights): preserve breakdown order in saved results",
    priority: "P3",
    summary:
      "Saved insights lose their breakdown order when reopened from a shared link. Readers see a different first series than the author did.",
    implementation_pr_url: null,
  }),
];

function menu(item: TaskActivityItem): TaskRowMenuProps {
  return {
    kind: "task",
    id: item.taskId,
    title: item.taskTitle,
    isPinned: false,
    onTogglePin: () => {},
    onArchive: () => {},
  };
}

function RailRows(): React.JSX.Element {
  const optionValues = [
    ...sessions.map((s) => `task:${s.id}`),
    ...reports.map((r) => `report:${r.id}`),
    "more",
  ];
  return (
    <Autocomplete<string> inline open items={optionValues} filter={null}>
      <AutocompleteList className="sidebar-autocomplete-tree !max-h-none !p-1.5 flex flex-col gap-px">
        <MenuLabel>Today</MenuLabel>
        {sessions.slice(0, 3).map((item) => (
          <ActivityRow
            key={item.id}
            item={item}
            menu={menu(item)}
            onMarkRead={() => {}}
            onActivate={() => {}}
            currentUser={ME}
            blockedTaskIds={new Set(["t2"])}
            compact
            asOption
            optionValue={`task:${item.id}`}
            isSelected={item.id === "a2"}
          />
        ))}
        {reports.map((report) => (
          <InboxActivityRow
            key={report.id}
            report={report}
            compact
            asOption
            optionValue={`report:${report.id}`}
            onActivate={() => {}}
          />
        ))}
        <InboxActivityOverflowRow count={7} asOption optionValue="more" />
        <MenuLabel>Yesterday</MenuLabel>
        {sessions.slice(3).map((item) => (
          <ActivityRow
            key={item.id}
            item={item}
            menu={menu(item)}
            onMarkRead={() => {}}
            onActivate={() => {}}
            currentUser={ME}
            blockedTaskIds={new Set()}
            compact
            asOption
            optionValue={`task:${item.id}`}
          />
        ))}
      </AutocompleteList>
    </Autocomplete>
  );
}

const meta: Meta<typeof RailRows> = {
  title: "Activity/Rail rows",
  component: RailRows,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story, context) => {
      const railWidth =
        typeof context.parameters.railWidth === "number"
          ? context.parameters.railWidth
          : CHANNELS_SIDEBAR_MIN_WIDTH;
      return (
        <div
          className={cn(
            RAIL_CONTAINER_CLASS,
            "h-[640px] border-border border-r bg-chrome",
          )}
          style={{ width: railWidth }}
        >
          <Story />
        </div>
      );
    },
  ],
};

export default meta;

type Story = StoryObj<typeof RailRows>;

export const DefaultWidth: Story = {};

export const At400px: Story = { parameters: { railWidth: 400 } };

export const At560px: Story = { parameters: { railWidth: 560 } };

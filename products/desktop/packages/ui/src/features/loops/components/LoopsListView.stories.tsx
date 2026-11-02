import type { UserBasic } from "@posthog/shared/domain-types";
import type { LoopSchemas } from "@posthog/ui/features/loops/loopSchemas";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { LoopSpace } from "../loopScopes";
import { LoopsListViewPresentation } from "./LoopsListView";

const POSTHOG_HOG: UserBasic = {
  id: 2,
  uuid: "user-posthog-hog",
  email: "hog@example.com",
  first_name: "PostHog",
  last_name: "Hog",
};

const PAUL: UserBasic = {
  id: 3,
  uuid: "user-paul",
  email: "paul@example.com",
  first_name: "Paul",
  last_name: "Bean",
};

function notifications(
  enabled: Array<keyof LoopSchemas.LoopNotifications>,
  slackChannel = "loops-alerts",
): LoopSchemas.LoopNotifications {
  return {
    email: { enabled: enabled.includes("email"), params: {} },
    slack: {
      enabled: enabled.includes("slack"),
      params: { channel_id: "C012345", channel_name: slackChannel },
    },
  };
}

const SPACES: LoopSpace[] = [
  { id: "space-growth", name: "growth", channelType: "public" },
  { id: "space-me", name: "me", channelType: "personal" },
];

function inSpace(space: LoopSpace): LoopSchemas.LoopContextTarget {
  return { channel_id: space.id, name: space.name };
}

function loop(
  id: string,
  overrides: Partial<LoopSchemas.Loop> = {},
): LoopSchemas.Loop {
  return {
    id,
    team_id: 2,
    created_by_id: POSTHOG_HOG.id,
    name: `Loop ${id}`,
    description: "",
    instructions: "Review recent activity and report anything notable.",
    runtime_adapter: "claude",
    model: "claude-sonnet-4-5",
    reasoning_effort: null,
    repositories: [],
    enabled: true,
    notifications: notifications([]),
    context_target: null,
    last_run_at: null,
    last_run_status: null,
    created_at: "2026-07-20T12:00:00Z",
    updated_at: "2026-07-20T12:00:00Z",
    triggers: [
      {
        id: `trigger-${id}`,
        loop_id: id,
        type: "schedule",
        enabled: true,
        config: { cron_expression: "0 9 * * 1-5", timezone: "UTC" },
        created_at: "2026-07-20T12:00:00Z",
        updated_at: "2026-07-20T12:00:00Z",
      },
    ],
    ...overrides,
  };
}

const MIXED_LOOPS: LoopSchemas.Loop[] = [
  loop("global-email", {
    name: "Daily product pulse",
    notifications: notifications(["email"]),
  }),
  loop("global-long", {
    name: "A very long loop name that tests truncation without displacing status badges or navigation",
    description:
      "This intentionally long description verifies that creator and notification metadata remain visible while descriptive copy truncates independently.",
    notifications: notifications(["email"]),
  }),
  loop("team-slack", {
    name: "Agentic-detection rollout monitoring",
    context_target: inSpace(SPACES[0]),
    notifications: notifications(["slack"], "agentic-rollout"),
  }),
  loop("team-all", {
    name: "Production incident watch",
    created_by_id: PAUL.id,
    notifications: notifications(["email", "slack"], "incidents"),
  }),
  loop("team-none", {
    name: "Paused loop without notifications",
    enabled: false,
    context_target: inSpace(SPACES[0]),
  }),
  loop("team-personal-space", {
    name: "Open PRs digest",
    context_target: inSpace(SPACES[1]),
  }),
  loop("team-gone-space", {
    name: "Loop in a space that was deleted",
    context_target: { channel_id: "space-gone", name: "old-team" },
  }),
  loop("team-former-owner", {
    name: "Loop owned by a former organization member",
    created_by_id: 999,
    last_run_status: "failed",
    notifications: notifications(["email"]),
  }),
];

const meta: Meta<typeof LoopsListViewPresentation> = {
  title: "Loops/LoopsListView",
  component: LoopsListViewPresentation,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <div className="h-screen w-full">
        <Story />
      </div>
    ),
  ],
  args: {
    loops: MIXED_LOOPS,
    spaces: SPACES,
    members: [POSTHOG_HOG, PAUL],
    onStartBlank: () => {},
    onStartFromTemplate: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof LoopsListViewPresentation>;

export const Comprehensive: Story = {};

export const LongMixedList: Story = {
  args: {
    loops: Array.from({ length: 18 }, (_, index) => {
      const channels: Array<keyof LoopSchemas.LoopNotifications> = [];
      if (index % 4 === 0) channels.push("email");
      if (index % 3 === 0) channels.push("slack");
      return loop(`long-list-${index + 1}`, {
        name: `Loop ${String(index + 1).padStart(2, "0")} · ${index % 2 === 0 ? "Monitor product health" : "Summarize customer feedback"}`,
        context_target: index % 3 === 0 ? inSpace(SPACES[index % 2]) : null,
        enabled: index % 7 !== 0,
        notifications: notifications(channels, `team-loop-${index + 1}`),
      });
    }),
  },
};

export const OnlySpaceLoops: Story = {
  args: {
    loops: MIXED_LOOPS.filter((entry) => entry.context_target !== null),
  },
};

export const WithBuilderSessions: Story = {
  args: {
    builderSessions: [
      {
        taskId: "builder-task-1",
        prompt: "Summarize my open PRs every weekday morning",
        startedAt: 1752000000000,
        identity: "us:2",
      },
      {
        taskId: "builder-task-2",
        prompt: "Build a loop",
        startedAt: 1752000600000,
        identity: "us:2",
      },
    ],
    onResumeBuilderSession: () => {},
    onBuilderSessionStopped: () => {},
  },
};

import type { ScoutConfig, ScoutRun } from "@posthog/api-client/posthog-client";
import {
  buildScoutCreatorIndex,
  computeScoutRollups,
  listScoutsNeedingAttention,
  sortConfigsForDisplay,
} from "@posthog/core/scouts/scoutPresentation";
import { AgentsTabLayout } from "@posthog/ui/features/agents/components/AgentsTabLayout";
import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ReactNode } from "react";
import { ScoutAttentionStrip } from "./ScoutAttentionStrip";
import { ScoutTable } from "./ScoutTable";

// Invented agents on invented people. Nothing here comes from a real project.
const ROBIN = {
  id: 1,
  first_name: "Robin",
  last_name: "Hedge",
  email: "robin@example.com",
};
const ALEX = {
  id: 2,
  first_name: "Alex",
  last_name: "Doe",
  email: "alex@example.com",
};

const NOW = new Date("2026-07-09T09:00:00Z");

function config(overrides: Partial<ScoutConfig> = {}): ScoutConfig {
  return {
    id: `config-${overrides.skill_name ?? "x"}`,
    skill_name: "signals-scout-error-tracking",
    enabled: true,
    emit: true,
    scout_origin: "canonical",
    run_interval_minutes: 180,
    auto_pause_exempt: false,
    created_at: "2026-06-01T00:00:00Z",
    ...overrides,
  };
}

const CONFIGS: ScoutConfig[] = [
  config({
    skill_name: "signals-scout-checkout-funnel",
    scout_origin: "custom",
    run_interval_minutes: 480,
    description: "Tracks conversion through the checkout funnel.",
  }),
  config({
    skill_name: "signals-scout-ad-spend",
    scout_origin: "custom",
    emit: false,
    description: "Watches ad spend events for runaway campaigns.",
  }),
  config({
    skill_name: "signals-scout-error-tracking",
    description: "Sweeps error tracking for new and spiking issues.",
  }),
  config({
    skill_name: "signals-scout-web-analytics",
    run_cron_schedule: "0 8 * * 4",
    description: "Looks for traffic anomalies across web analytics.",
  }),
  config({
    skill_name: "signals-scout-session-replay",
    run_interval_minutes: 1440,
    description: "Reads replays for friction on the newest release.",
  }),
  config({
    skill_name: "signals-scout-weekly-digest",
    scout_origin: "custom",
    enabled: false,
    status: "paused_by_system",
    pause_reason: "repeated_failures",
    consecutive_failure_count: 3,
    description: "Sums up the week for the product team.",
  }),
];

function run(overrides: Partial<ScoutRun> & { skill_name: string }): ScoutRun {
  return {
    run_id: `run-${Math.random().toString(36).slice(2)}`,
    skill_version: 1,
    status: "completed",
    started_at: "2026-07-09T06:30:00Z",
    completed_at: "2026-07-09T06:34:00Z",
    task_id: null,
    task_run_id: null,
    task_url: "/project/1/tasks/example-task?runId=example-run",
    summary: "Nothing worth sending this time.",
    emitted_count: 0,
    emitted_finding_ids: [],
    ...overrides,
  };
}

const RUNS: ScoutRun[] = [
  ...Array.from({ length: 12 }, (_, index) =>
    run({
      skill_name: "signals-scout-checkout-funnel",
      emitted_count: index % 4 === 0 ? 1 : 0,
      started_at: new Date(NOW.getTime() - index * 3_600_000).toISOString(),
    }),
  ),
  ...Array.from({ length: 9 }, (_, index) =>
    run({
      skill_name: "signals-scout-error-tracking",
      status: index === 0 ? "in_progress" : "completed",
      completed_at: index === 0 ? null : "2026-07-09T05:20:00Z",
      emitted_count: index % 3 === 0 ? 2 : 0,
      started_at: new Date(NOW.getTime() - index * 7_200_000).toISOString(),
    }),
  ),
  ...Array.from({ length: 6 }, (_, index) =>
    run({
      skill_name: "signals-scout-weekly-digest",
      status: "failed",
      summary: "The query timed out.",
      started_at: new Date(NOW.getTime() - index * 86_400_000).toISOString(),
    }),
  ),
  ...Array.from({ length: 4 }, (_, index) =>
    run({
      skill_name: "signals-scout-web-analytics",
      started_at: new Date(NOW.getTime() - index * 86_400_000).toISOString(),
    }),
  ),
];

const ROLLUPS = computeScoutRollups(RUNS);
const CREATORS = buildScoutCreatorIndex([
  {
    name: "signals-scout-checkout-funnel",
    created_by: ROBIN,
    is_latest: true,
  },
  { name: "signals-scout-ad-spend", created_by: ALEX, is_latest: true },
  { name: "signals-scout-weekly-digest", created_by: ROBIN, is_latest: true },
]);
const ORDERED = sortConfigsForDisplay(CONFIGS);
const ATTENTION = listScoutsNeedingAttention(CONFIGS, ROLLUPS, NOW);

/**
 * A row builds a "run now" action, which needs a signed-in client to exist.
 * The story never calls it, so a region and a project are enough.
 */
function SignedIn({ children }: { children: ReactNode }) {
  useAuthStore.setState({
    authState: {
      ...ANONYMOUS_AUTH_STATE,
      status: "authenticated",
      cloudRegion: "us",
      currentProjectId: 1,
    },
  });
  return <>{children}</>;
}

const meta = {
  title: "Scouts/ScoutTable",
  component: ScoutTable,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <SignedIn>
        <Story />
      </SignedIn>
    ),
  ],
} satisfies Meta<typeof ScoutTable>;

export default meta;

type Story = StoryObj<typeof meta>;

const noop = () => undefined;

/** The Agents tab of the Agents settings page: what needs a decision, then the fleet. */
export const AgentsTab: Story = {
  render: () => (
    <div className="h-[42rem]">
      <AgentsTabLayout tab="agents" fill count={CONFIGS.length}>
        <ScoutAttentionStrip items={ATTENTION} onUpdateConfig={noop} />
        <ScoutTable
          configs={ORDERED}
          rollups={ROLLUPS}
          runsPending={false}
          creators={CREATORS}
          onUpdateConfig={noop}
          emptyMessage="No agents match these filters."
        />
      </AgentsTabLayout>
    </div>
  ),
};

/** The table on its own, with run history still on its way. */
export const RunsLoading: Story = {
  render: () => (
    <div className="h-[32rem] p-6">
      <ScoutTable
        configs={ORDERED}
        rollups={new Map()}
        runsPending
        creators={CREATORS}
        onUpdateConfig={noop}
        emptyMessage="No agents match these filters."
      />
    </div>
  ),
};

/** Every agent filtered out. */
export const NoMatches: Story = {
  render: () => (
    <div className="h-[20rem] p-6">
      <ScoutTable
        configs={[]}
        rollups={ROLLUPS}
        runsPending={false}
        creators={CREATORS}
        onUpdateConfig={noop}
        emptyMessage="No agents match these filters."
      />
    </div>
  ),
};

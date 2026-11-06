import type { ScoutConfig, ScoutRun } from "@posthog/api-client/posthog-client";
import { computeScoutRollups } from "@posthog/core/scouts/scoutPresentation";
import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ReactNode } from "react";
import { ScoutDetailHeader } from "./ScoutDetailHeader";

const NOW = new Date("2026-07-09T09:00:00Z");

// An invented agent. Nothing here comes from a real project.
const CONFIG: ScoutConfig = {
  id: "config-checkout-funnel",
  skill_name: "signals-scout-checkout-funnel",
  enabled: true,
  emit: true,
  scout_origin: "custom",
  run_interval_minutes: 480,
  auto_pause_exempt: false,
  created_at: "2026-06-01T00:00:00Z",
  last_run_at: "2026-07-09T06:30:00Z",
  description:
    "Watches conversion through the checkout funnel and sends a signal when a step drops against its own two-week baseline.",
};

const RUNS: ScoutRun[] = Array.from({ length: 14 }, (_, index) => ({
  run_id: `run-${index}`,
  skill_name: CONFIG.skill_name,
  skill_version: 1,
  status: "completed",
  started_at: new Date(NOW.getTime() - index * 28_800_000).toISOString(),
  completed_at: new Date(
    NOW.getTime() - index * 28_800_000 + 240_000,
  ).toISOString(),
  task_id: null,
  task_run_id: null,
  task_url: null,
  summary: "Checked every step. Nothing moved outside the baseline.",
  emitted_count: index % 5 === 0 ? 1 : 0,
  emitted_finding_ids: [],
}));

const ROLLUP = computeScoutRollups(RUNS).get(CONFIG.skill_name);

/** The header builds a "run now" action, which needs a signed-in client to exist. */
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

const noop = () => undefined;

const meta = {
  title: "Scouts/ScoutDetailHeader",
  component: ScoutDetailHeader,
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <SignedIn>
        <Story />
      </SignedIn>
    ),
  ],
  args: {
    config: CONFIG,
    configLoading: false,
    displayName: "Checkout funnel",
    rollup: ROLLUP,
    onUpdate: noop,
    tab: "activity" as const,
    onTabChange: noop,
    onBack: noop,
  },
} satisfies Meta<typeof ScoutDetailHeader>;

export default meta;

type Story = StoryObj<typeof meta>;

/** What one agent's page opens on: who it is, when it runs, and how it has been doing. */
export const Header: Story = {};

/** The config request has not answered yet. */
export const Loading: Story = {
  args: { config: undefined, configLoading: true, rollup: undefined },
};

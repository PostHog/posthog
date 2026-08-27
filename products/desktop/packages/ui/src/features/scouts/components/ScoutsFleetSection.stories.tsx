import type { ScoutConfig, ScoutRun } from "@posthog/api-client/posthog-client";
import { buildScoutCreatorIndex } from "@posthog/core/scouts/scoutPresentation";
import type { ScoutRunsWindow } from "@posthog/core/scouts/scoutRunsWindow";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ScoutsFleetListView } from "./ScoutsFleetSection";

const YOU = {
  id: 1,
  first_name: "Robbie",
  last_name: "Hedgehog",
  email: "robbie@example.com",
};
const ALEX = {
  id: 2,
  first_name: "Alex",
  last_name: "Doe",
  email: "alex@example.com",
};
const SAM = { id: 3, first_name: "Sam", email: "sam@example.com" };

const config = (overrides: Partial<ScoutConfig> = {}): ScoutConfig => ({
  id: `config-${overrides.skill_name ?? "x"}`,
  skill_name: "signals-scout-error-tracking",
  enabled: true,
  emit: true,
  scout_origin: "canonical",
  run_interval_minutes: 180,
  last_run_at: "2026-07-09T06:30:00Z",
  auto_pause_exempt: false,
  created_at: "2026-06-01T00:00:00Z",
  ...overrides,
});

const CONFIGS: ScoutConfig[] = [
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
    run_interval_minutes: 1440,
    description: "Looks for traffic anomalies across web analytics.",
  }),
  config({
    skill_name: "signals-scout-checkout-funnel",
    scout_origin: "custom",
    run_interval_minutes: 480,
    description: "Tracks conversion through the checkout funnel.",
  }),
  config({
    skill_name: "signals-scout-weekly-digest",
    scout_origin: "custom",
    enabled: false,
    status: "paused_by_user",
    run_interval_minutes: 10080,
    description: "Posts a weekly digest of notable product metrics.",
  }),
];

/** The lifecycle states the platform drives, not the user. */
const LIFECYCLE_CONFIGS: ScoutConfig[] = [
  ...CONFIGS,
  // Quiet, so flagged for a look — but silence alone never pauses a scout.
  config({
    id: "config-quiet-watchdog",
    skill_name: "signals-scout-quiet-watchdog",
    scout_origin: "custom",
    status: "pending_pause",
    pause_reason: "no_output",
    status_changed_at: "2026-07-08T06:15:00Z",
    description: "Watches for a failure mode that has not fired in a while.",
  }),
  // Findings nobody picked up: this is the warning that does advance to a pause.
  config({
    id: "config-ignored-digest",
    skill_name: "signals-scout-ignored-digest",
    scout_origin: "custom",
    status: "pending_pause",
    pause_reason: "ignored",
    status_changed_at: "2026-07-08T06:15:00Z",
    description: "Files a digest of product metrics nobody has acted on.",
  }),
  config({
    id: "config-flaky-import",
    skill_name: "signals-scout-flaky-import",
    scout_origin: "custom",
    enabled: false,
    status: "paused_by_system",
    pause_reason: "repeated_failures",
    consecutive_failure_count: 6,
    status_changed_at: "2026-07-07T00:45:00Z",
    description: "Sweeps warehouse imports for stuck or failing syncs.",
  }),
];

// Authorship joins from the backing skills: canonical scouts carry no author.
const CREATORS = buildScoutCreatorIndex([
  { name: "signals-scout-ad-spend", created_by: YOU, is_latest: true },
  { name: "signals-scout-error-tracking", created_by: null, is_latest: true },
  { name: "signals-scout-web-analytics", created_by: null, is_latest: true },
  { name: "signals-scout-checkout-funnel", created_by: ALEX, is_latest: true },
  { name: "signals-scout-weekly-digest", created_by: SAM, is_latest: true },
]);

let runSeq = 0;
const run = (
  skillName: string,
  overrides: Partial<ScoutRun> = {},
): ScoutRun => ({
  run_id: `run-${++runSeq}`,
  skill_name: skillName,
  skill_version: 3,
  status: "completed",
  started_at: "2026-07-09T05:00:00Z",
  completed_at: "2026-07-09T05:03:00Z",
  task_id: null,
  task_run_id: null,
  task_url: null,
  summary: "EMITTED nothing.",
  emitted_count: 0,
  emitted_finding_ids: [],
  ...overrides,
});

const RUNS_WINDOW: ScoutRunsWindow = {
  complete: true,
  runs: [
    ...Array.from({ length: 6 }, (_, i) =>
      run("signals-scout-error-tracking", {
        emitted_count: i === 2 ? 1 : 0,
        ...(i === 4
          ? { status: "failed", completed_at: "2026-07-09T05:00:40Z" }
          : {}),
      }),
    ),
    ...Array.from({ length: 4 }, () => run("signals-scout-web-analytics")),
    ...Array.from({ length: 5 }, (_, i) =>
      run("signals-scout-ad-spend", { emitted_count: i === 0 ? 2 : 0 }),
    ),
    run("signals-scout-checkout-funnel"),
    run("signals-scout-checkout-funnel", {
      status: "failed",
      // Past the ~30m activity deadline, so it reads as a timeout.
      completed_at: "2026-07-09T05:31:00Z",
    }),
  ],
};

const meta: Meta<typeof ScoutsFleetListView> = {
  title: "Scouts/ScoutsFleetList",
  component: ScoutsFleetListView,
  args: {
    configs: CONFIGS,
    runsWindow: RUNS_WINDOW,
    creators: CREATORS,
    currentUser: YOU,
    onUpdateConfig: () => {},
  },
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 1160, margin: "2rem auto", padding: "0 1rem" }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ScoutsFleetListView>;

/** The expanded fleet: summary, filters (Created by + Hide disabled), CTAs, rows. */
export const Fleet: Story = {};

/** "Created by" preset to the current user → only their hand-authored scouts. */
export const FilteredToYou: Story = {
  args: { initialCreatorKey: `id:${YOU.id}` },
};

/** The current user has authored nothing → picker still offers them, list explains. */
export const NothingOfYours: Story = {
  args: {
    currentUser: { id: 99, first_name: "Newbie", email: "new@example.com" },
    initialCreatorKey: "id:99",
  },
};

/** Skills API gated for the org (creators = null) → no creator picker at all. */
export const WithoutCreatorData: Story = {
  args: { creators: null },
};

/**
 * The three system-driven states side by side: a quiet scout (flagged only), one
 * whose ignored findings will pause it, and one the failure breaker already
 * paused. Only the latter two are counted in the summary line, and the paused
 * one stays out of the "hide disabled" filter so it remains recoverable.
 */
export const SystemPaused: Story = {
  args: { configs: LIFECYCLE_CONFIGS },
};

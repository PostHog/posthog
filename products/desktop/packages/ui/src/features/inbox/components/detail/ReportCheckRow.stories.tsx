import {
  buildReportCheckRows,
  reportChecksMeta,
} from "@posthog/core/inbox/reportChecks";
import type { SignalReportCheck } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportCheckRow } from "./ReportCheckRow";

function makeCheck(overrides: Partial<SignalReportCheck>): SignalReportCheck {
  return {
    id: "check-1",
    title: "Checkout errors stay at zero",
    rationale: "The retry fix should stop the exception.",
    kind: "agent",
    status: "active",
    config: { skill_name: "signals-scout-error-tracking" },
    next_run_at: "2026-09-27T09:00:00Z",
    soak_minutes: 10080,
    run_interval_minutes: null,
    runs_remaining: 1,
    expires_at: "2026-10-27T09:00:00Z",
    last_run_at: null,
    last_outcome: null,
    dispatched_at: null,
    consecutive_errors: 0,
    created_at: "2026-09-20T09:00:00Z",
    updated_at: "2026-09-20T09:00:00Z",
    ...overrides,
  };
}

const CHECKS: SignalReportCheck[] = [
  makeCheck({ id: "running", dispatched_at: "2026-09-21T08:40:00Z" }),
  makeCheck({ id: "scheduled" }),
  makeCheck({
    id: "metric",
    kind: "metric_threshold",
    title: "Rageclicks stay under 20 a week",
    config: { comparison: { operator: "lte", value: 20 } },
    soak_minutes: null,
  }),
  makeCheck({ id: "waiting", status: "pending" }),
  makeCheck({
    id: "passed",
    status: "passed",
    last_run_at: "2026-09-19T09:00:00Z",
  }),
  makeCheck({
    id: "failed",
    status: "failed",
    last_run_at: "2026-09-19T09:00:00Z",
  }),
  makeCheck({
    id: "errored",
    status: "errored",
    consecutive_errors: 3,
    last_run_at: "2026-09-18T09:00:00Z",
  }),
  makeCheck({
    id: "expired",
    status: "expired",
    updated_at: "2026-09-17T09:00:00Z",
  }),
  makeCheck({
    id: "cancelled",
    status: "cancelled",
    updated_at: "2026-09-16T09:00:00Z",
  }),
];

const EXPLANATIONS = new Map([
  ["passed", "11 rageclicks in the last 14 days."],
  ["failed", "34 rageclicks in the last 14 days, up from 11."],
  ["errored", "The query timed out."],
]);

/** Every state a check row can read as, at the width the detail rail gives it. */
function AllStates({ width }: { width: number }) {
  const rows = buildReportCheckRows(CHECKS, EXPLANATIONS);
  return (
    <div className="flex flex-col gap-1.5" style={{ width }}>
      <span className="text-muted-foreground text-xs tabular-nums">
        {reportChecksMeta(CHECKS)}
      </span>
      {rows.map((row) => (
        <ReportCheckRow
          key={row.check.id}
          row={row}
          stopping={row.check.id === "scheduled"}
          onStop={() => {}}
        />
      ))}
    </div>
  );
}

const meta: Meta<typeof AllStates> = {
  title: "Inbox/Reports/Follow-up checks",
  component: AllStates,
  parameters: { layout: "padded" },
  args: { width: 416 },
};

export default meta;
type Story = StoryObj<typeof AllStates>;

export const EveryState: Story = {};

/** The width the rail keeps next to an open side panel. */
export const NarrowRail: Story = { args: { width: 320 } };

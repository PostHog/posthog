import type {
  Signal,
  SignalReport,
  Task,
  TaskRunStatus,
} from "@posthog/shared/types";

export function inboxStoryReport(
  overrides: Partial<SignalReport> = {},
): SignalReport {
  return {
    id: "story-report",
    title: "fix(cohorts): keep recurring calculations within their budget",
    summary:
      "Recurring cohort calculations can overlap after a delayed run, which increases queue time for later updates.\n\n## Impact\n\nTeams see stale cohort membership until the overlapping calculations finish.\n\n## Recommendation\n\nCoalesce pending work by cohort and carry the newest requested calculation forward.",
    status: "ready",
    total_weight: 48,
    signal_count: 6,
    created_at: "2026-08-20T09:00:00Z",
    updated_at: "2026-08-28T14:30:00Z",
    artefact_count: 3,
    priority: "P1",
    actionability: "immediately_actionable",
    is_suggested_reviewer: true,
    source_products: ["signals_scout"],
    ...overrides,
  };
}

export function inboxStorySignal(overrides: Partial<Signal> = {}): Signal {
  return {
    signal_id: "story-signal",
    content:
      "The calculated membership remained unchanged after the scheduled update completed.",
    source_product: "signals_scout",
    source_type: "cross_source_issue",
    source_id: "story-source",
    weight: 8,
    timestamp: "2026-08-27T12:00:00Z",
    extra: { skill_name: "signals-scout-data-quality" },
    ...overrides,
  };
}

export function inboxStoryImplementation(
  id: string,
  status: TaskRunStatus,
  overrides: Partial<SignalReport> = {},
): { report: SignalReport; task: Task } {
  const report = inboxStoryReport({
    id,
    assignee: { kind: "task", task_id: `task-${id}` },
    ...overrides,
  });
  const task: Task = {
    id: `task-${id}`,
    task_number: 1,
    slug: `task-${id}`,
    title: report.title ?? "Implement the report",
    description: "Create a PR for the report.",
    origin_product: "signal_report",
    created_at: report.created_at,
    updated_at: report.created_at,
    latest_run: {
      id: `run-${id}`,
      task: `task-${id}`,
      team: 1,
      branch: null,
      status,
      log_url: "",
      error_message: status === "failed" ? "The task could not finish." : null,
      output: null,
      state: {},
      created_at: report.created_at,
      updated_at: report.created_at,
      completed_at: null,
    },
  };
  return { report, task };
}

export const inboxStoryImplementations = [
  inboxStoryImplementation("working", "in_progress", {
    title: "fix(cohorts): coalesce pending calculations",
  }),
  inboxStoryImplementation("failed", "failed", {
    title: "fix(flags): retry a failed evaluation",
    summary:
      "Flag evaluation fails after a connection closes. Retry the request after reconnecting.",
  }),
  inboxStoryImplementation("waiting", "in_progress", {
    title: "feat(insights): choose a default breakdown order",
    summary:
      "The task needs a choice between alphabetical order and ranking by value before it can update the saved insight.",
    status: "pending_input",
    actionability: "requires_human_input",
  }),
  inboxStoryImplementation("cancelled", "cancelled", {
    title: "fix(webhooks): resume delivery after a timeout",
    summary:
      "Webhook delivery stops after a timeout. The implementation task stopped before it could add a retry.",
  }),
  inboxStoryImplementation("no-pr", "completed", {
    title: "fix(replay): show buffer health in the player",
    summary:
      "The player does not show when its buffer is empty. The task finished its investigation but did not create a PR.",
  }),
];

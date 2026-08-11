import type { SignalReport } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react";
import type { ReactNode } from "react";
import { ReportCardView } from "./ReportCard";

const report = (overrides: Partial<SignalReport> = {}): SignalReport => ({
  id: "story-report",
  title: "fix(replay): buffer underruns stall playback on long sessions",
  summary:
    "Playback stalls at snapshot gaps longer than the buffer window. Several long sessions this week hit the stall within the first minute.",
  status: "ready",
  total_weight: 40,
  signal_count: 7,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-06T10:00:00Z",
  artefact_count: 1,
  priority: "P2",
  actionability: "immediately_actionable",
  is_suggested_reviewer: true,
  source_products: ["session_replay"],
  ...overrides,
});

const containerAt = (width: number) => (Story: () => ReactNode) => (
  <div className="@container" style={{ width }}>
    <Story />
  </div>
);

const meta: Meta<typeof ReportCardView> = {
  title: "Inbox/ReportCard",
  component: ReportCardView,
  args: {
    report: report(),
    artefacts: null,
    renderBody: (body, className) => <div className={className}>{body}</div>,
  },
  decorators: [containerAt(800)],
};
export default meta;

type Story = StoryObj<typeof ReportCardView>;

export const Wide: Story = {};

/** Long conventional-commit title wraps under the inline scope tag. */
export const WrappingTitle: Story = {
  args: {
    report: report({
      title:
        "fix(replay): buffer underruns stall playback on long sessions when the snapshot gap exceeds the prefetch window on slow connections",
    }),
  },
};

/** Below the `@lg` container breakpoint the card stacks and the rail border disappears. */
export const Narrow: Story = {
  decorators: [containerAt(420)],
};

/** Still-researching report: no headline yet, dimmed status. */
export const Pending: Story = {
  args: {
    report: report({
      status: "in_progress",
      summary: null,
      actionability: null,
      priority: null,
    }),
  },
};

/** Archived report: dimmed, restore-only rail, dismissal reason chip. */
export const Archived: Story = {
  args: {
    variant: "archived",
    report: report({
      status: "suppressed",
      dismissal_reason: "analysis_wrong",
      dismissal_note: "Known issue, tracked elsewhere.",
    }),
  },
};

/** Resolved report: terminal, reference-only, no actions rail at all. */
export const Resolved: Story = {
  args: {
    variant: "archived",
    report: report({ status: "resolved" }),
  },
};

export const NarrowArchived: Story = {
  args: {
    variant: "archived",
    report: report({
      status: "suppressed",
      dismissal_reason: "analysis_wrong",
    }),
  },
  decorators: [containerAt(420)],
};

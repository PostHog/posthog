import type {
  SignalReport,
  SignalReportArtefactsResponse,
  SuggestedReviewersArtefact,
} from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react";
import type { ReactNode } from "react";
import { PullRequestCardView } from "./PullRequestCard";

const report = (overrides: Partial<SignalReport> = {}): SignalReport => ({
  id: "story-pr-report",
  title: "fix(product-tours): guard step anchors against removed DOM nodes",
  summary:
    "Users abandoning a tour mid-step leave the anchor detached, which crashes the next step render. The fix re-resolves anchors lazily.",
  status: "ready",
  total_weight: 60,
  signal_count: 12,
  created_at: "2026-08-01T10:00:00Z",
  updated_at: "2026-08-06T10:00:00Z",
  artefact_count: 2,
  priority: "P1",
  actionability: "immediately_actionable",
  source_products: ["error_tracking"],
  implementation_pr_url: "https://github.com/PostHog/posthog/pull/12345",
  ...overrides,
});

const reviewersArtefact: SuggestedReviewersArtefact = {
  id: "artefact-reviewers",
  created_at: "2026-08-06T10:00:00Z",
  type: "suggested_reviewers",
  content: [
    {
      github_login: "example-reviewer",
      github_name: "Example Reviewer",
      relevant_commits: [],
      user: null,
    },
  ],
};

const reviewers: SignalReportArtefactsResponse = {
  results: [reviewersArtefact],
  count: 1,
};

/**
 * Cards read their breakpoint from an `@container` ancestor (the list shell in
 * the app). Wide shows the rail layout, narrow the stacked layout.
 */
const containerAt = (width: number) => (Story: () => ReactNode) => (
  <div className="@container" style={{ width }}>
    <Story />
  </div>
);

const meta: Meta<typeof PullRequestCardView> = {
  title: "Inbox/PullRequestCard",
  component: PullRequestCardView,
  args: {
    report: report(),
    repoSlug: "PostHog/posthog",
    artefacts: reviewers,
    renderBody: (body, className) => <div className={className}>{body}</div>,
  },
  decorators: [containerAt(800)],
};
export default meta;

type Story = StoryObj<typeof PullRequestCardView>;

export const Wide: Story = {};

/**
 * A two-line title must start on the same line as the scope tag and wrap
 * beneath it, not center vertically beside it.
 */
export const WrappingTitle: Story = {
  args: {
    report: report({
      title:
        "fix(product-tours): guard step anchors against removed DOM nodes so abandoned tours no longer crash the next step render",
    }),
  },
};

/** Below the `@lg` container breakpoint the card stacks and the rail border disappears. */
export const Narrow: Story = {
  decorators: [containerAt(420)],
};

export const NarrowWrappingTitle: Story = {
  args: WrappingTitle.args,
  decorators: [containerAt(420)],
};

export const Selected: Story = {
  args: { isSelected: true },
};

export const DismissPending: Story = {
  args: { isDismissPending: true },
};

/** No repo/artefact data yet: meta row collapses to what the report carries. */
export const MinimalData: Story = {
  args: {
    report: report({
      title: "Untitled pull request",
      summary: null,
      priority: null,
      actionability: null,
      source_products: [],
    }),
    repoSlug: null,
    artefacts: null,
  },
};

import type { SignalReport } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { PullRequestCard } from "./PullRequestCard";

const report = (overrides: Partial<SignalReport> = {}): SignalReport => ({
  id: "report-pr-1",
  title:
    "fix(product-tours): scope tour delivery consistently and stop silent preview failures",
  summary:
    "A customer set up a product tour banner and can see neither the in-app preview nor the banner on their own site, and both failures come down to delivery scoping.",
  status: "ready",
  total_weight: 4,
  signal_count: 3,
  created_at: "2026-08-01T09:00:00Z",
  updated_at: "2026-08-05T16:30:00Z",
  artefact_count: 2,
  priority: "P1",
  actionability: "immediately_actionable",
  source_products: ["conversations"],
  implementation_pr_url: "https://github.com/example-org/example-repo/pull/123",
  ...overrides,
});

const meta: Meta<typeof PullRequestCard> = {
  title: "Inbox/PullRequestCard",
  component: PullRequestCard,
  args: {
    report: report(),
    onDismiss: () => {},
  },
};
export default meta;
type Story = StoryObj<typeof PullRequestCard>;

/**
 * A long conventional-commit title wraps beneath its inline type tag instead
 * of centering the tag against the wrapped block.
 */
export const WrappingTitle: Story = {
  decorators: [
    (StoryFn) => (
      <div
        className="@container"
        style={{ maxWidth: 720, margin: "2rem auto", padding: "0 1rem" }}
      >
        <StoryFn />
      </div>
    ),
  ],
};

/** Below ~32rem of card width the actions rail stacks under the content. */
export const Narrow: Story = {
  decorators: [
    (StoryFn) => (
      <div
        className="@container"
        style={{ maxWidth: 360, margin: "2rem auto", padding: "0 1rem" }}
      >
        <StoryFn />
      </div>
    ),
  ],
};

export const Selected: Story = {
  args: { isSelected: true },
  decorators: [
    (StoryFn) => (
      <div
        className="@container"
        style={{ maxWidth: 720, margin: "2rem auto", padding: "0 1rem" }}
      >
        <StoryFn />
      </div>
    ),
  ],
};

import type { Signal } from "@posthog/shared/types";
import type { Meta, StoryObj } from "@storybook/react";
import { SignalsList } from "./SignalsList";

const meta: Meta<typeof SignalsList> = {
  title: "Inbox/SignalsList",
  component: SignalsList,
  decorators: [
    (Story) => (
      <div style={{ maxWidth: 420 }}>
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof SignalsList>;

let seq = 0;
function signal(overrides: Partial<Signal>): Signal {
  seq += 1;
  return {
    signal_id: `sig-${seq}`,
    content: "Checkout requests started returning 502s after the deploy.",
    source_product: "error_tracking",
    source_type: "issue_created",
    source_id: `src-${seq}`,
    weight: 1,
    timestamp: "2026-07-30T14:00:00Z",
    extra: { fingerprint: `fp-${seq}` },
    ...overrides,
  };
}

const githubIssue = (n: number): Signal =>
  signal({
    source_product: "github",
    source_type: "issue",
    content: `Users report the export button does nothing on large projects (#${n}).`,
    extra: {
      html_url: `https://github.com/acme/app/issues/${n}`,
      number: n,
      labels: [{ name: "bug", color: "d73a4a" }],
      created_at: "2026-07-29T09:00:00Z",
    },
  });

/** Many findings, few types: the grouped view with counts per type. */
export const Grouped: Story = {
  args: {
    signals: [
      signal({}),
      signal({ content: "TypeError: cannot read properties of undefined." }),
      signal({
        source_type: "issue_spiking",
        content: "502 volume spiked 8x.",
      }),
      signal({}),
      signal({
        source_type: "issue_spiking",
        content: "Timeout volume spiked.",
      }),
      githubIssue(101),
      githubIssue(102),
      signal({
        source_product: "llm_analytics",
        source_type: "evaluation",
        content: "Evaluation score dropped below threshold on the support bot.",
        extra: { evaluation_id: "eval-1", trace_id: "trace-abc123456789" },
      }),
      signal({}),
    ],
  },
};

/** Below the grouping threshold: the flat list. */
export const Flat: Story = {
  args: {
    signals: [signal({}), githubIssue(103)],
  },
};

/** Enough findings but every type distinct: grouping would not compress, stays flat. */
export const FlatAllDistinctTypes: Story = {
  args: {
    signals: [
      signal({}),
      signal({ source_type: "issue_spiking" }),
      githubIssue(104),
      signal({
        source_product: "zendesk",
        source_type: "ticket",
        content: "Customer cannot log in since this morning.",
        extra: {
          url: "https://acme.zendesk.com/api/v2/tickets/42.json",
          priority: "high",
          status: "open",
        },
      }),
      signal({
        source_product: "llm_analytics",
        source_type: "evaluation",
        content: "Hallucination rate above target.",
        extra: { evaluation_id: "eval-2", trace_id: "trace-def123456789" },
      }),
    ],
  },
};

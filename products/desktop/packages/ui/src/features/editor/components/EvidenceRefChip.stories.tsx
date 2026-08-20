import {
  EvidenceHoverCard,
  EvidenceRefChip,
} from "@posthog/ui/features/editor/components/EvidenceRefChip";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof EvidenceRefChip> = {
  title: "Features/Editor/EvidenceRefChip",
  component: EvidenceRefChip,
  parameters: {
    layout: "padded",
  },
};

export default meta;
type Story = StoryObj<typeof EvidenceRefChip>;

export const AllKinds: Story = {
  render: () => (
    <div className="flex max-w-md flex-col items-start gap-2 text-[13px]">
      <EvidenceRefChip target={{ kind: "insight", id: "9pQx3" }}>
        Checkout funnel
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "dashboard", id: "12" }}>
        Growth dashboard
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "error", id: "018f44aa-9c2b" }}>
        CouponValidator TypeError
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "replay", id: "s_01HQ4K" }}>
        14 rageclick recordings
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "flag", id: "new-checkout-flow" }}>
        new-checkout-flow
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "experiment", id: "42" }}>
        Reminder timing experiment
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "survey", id: "srv_11" }}>
        Checkout survey verbatims
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "ticket", id: "conv_88" }}>
        9 “coupon” tickets
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "trace", id: "t_9f2ab4" }}>
        Slow generation traces
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "eval", id: "ev_faith" }}>
        Faithfulness eval
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "event", id: "cart_saved" }}>
        cart_saved events
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "cohort", id: "31" }}>
        Power users cohort
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "action", id: "5" }}>
        Clicked upgrade action
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "person", id: "0192-aaaa" }}>
        the affected user
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "something-new", id: "x1" }}>
        Unknown kind falls back
      </EvidenceRefChip>
    </div>
  ),
};

/**
 * The hover card resolves the object live when opened. These stories render
 * the card itself in each state: loading, resolved, and the static fallback
 * when nothing can be fetched.
 */
export const HoverCardStates: Story = {
  render: () => (
    <div className="flex flex-wrap items-start gap-4">
      <div className="rounded-md border border-(--gray-a5) bg-(--color-panel-solid)">
        <EvidenceHoverCard
          target={{ kind: "insight", id: "9pQx3" }}
          url={null}
          preview={undefined}
          onExpand={() => {}}
        >
          Checkout funnel
        </EvidenceHoverCard>
      </div>
      <div className="rounded-md border border-(--gray-a5) bg-(--color-panel-solid)">
        <EvidenceHoverCard
          target={{ kind: "insight", id: "9pQx3" }}
          url="https://us.posthog.com/project/2/insights/9pQx3"
          preview={{
            title: "Coupon → purchase conversion",
            detail: "Funnel conversion, last 30 days",
          }}
          onExpand={() => {}}
        >
          Checkout funnel
        </EvidenceHoverCard>
      </div>
      <div className="rounded-md border border-(--gray-a5) bg-(--color-panel-solid)">
        <EvidenceHoverCard
          target={{ kind: "flag", id: "new-checkout-flow" }}
          url={null}
          preview={{
            title: "new-checkout-flow",
            detail: "Enabled · New checkout rollout",
            facts: ["100% rollout", "Used by 1 experiment"],
          }}
          onExpand={() => {}}
        >
          new-checkout-flow
        </EvidenceHoverCard>
      </div>
      <div className="rounded-md border border-(--gray-a5) bg-(--color-panel-solid)">
        <EvidenceHoverCard
          target={{ kind: "hogql", id: "SELECT toDate(timestamp) AS day ..." }}
          url="https://us.posthog.com/project/2/sql"
          preview={{
            title: "active_users",
            headline: {
              value: "1.5M",
              delta: { label: "71%", direction: "down" },
            },
            spark: {
              points: [4.9, 5.1, 5.7, 5.8, 5.7, 5.1, 1.5],
              render: "line",
            },
          }}
          onExpand={() => {}}
        >
          active users per day
        </EvidenceHoverCard>
      </div>
      <div className="rounded-md border border-(--gray-a5) bg-(--color-panel-solid)">
        <EvidenceHoverCard
          target={{ kind: "ticket", id: "conv_88" }}
          url="https://us.posthog.com/project/2/insights/9pQx3"
          preview={null}
          onExpand={() => {}}
        >
          9 “coupon” tickets
        </EvidenceHoverCard>
      </div>
    </div>
  ),
};

export const InsideAgentMessage: Story = {
  render: () => (
    <div className="max-w-xl">
      <MarkdownRenderer
        content={[
          'The <insight id="9pQx3">coupon → purchase conversion</insight> dropped',
          "41% → 28% on Jan 3, the same day",
          '<error id="018f44aa">a TypeError in CouponValidator</error> first',
          'appeared, and <replay id="s_01HQ4K">14 recordings</replay> show users',
          "retrying the field before leaving. This area is gated by",
          '<flag id="42">new-checkout-flow</flag>, and',
          "<hogql label=\"1,247 sessions\">SELECT count(distinct $session_id) FROM events WHERE event = '$exception'</hogql>",
          "hit the error this week.",
        ].join(" ")}
      />
    </div>
  ),
};

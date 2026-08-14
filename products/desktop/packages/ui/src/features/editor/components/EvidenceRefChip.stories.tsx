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
          clickable={false}
          preview={undefined}
        >
          Checkout funnel
        </EvidenceHoverCard>
      </div>
      <div className="rounded-md border border-(--gray-a5) bg-(--color-panel-solid)">
        <EvidenceHoverCard
          target={{ kind: "insight", id: "9pQx3" }}
          clickable={true}
          preview={{
            title: "Coupon → purchase conversion",
            detail: "Funnel conversion, last 30 days",
          }}
        >
          Checkout funnel
        </EvidenceHoverCard>
      </div>
      <div className="rounded-md border border-(--gray-a5) bg-(--color-panel-solid)">
        <EvidenceHoverCard
          target={{ kind: "flag", id: "new-checkout-flow" }}
          clickable={false}
          preview={{
            title: "new-checkout-flow",
            detail: "Enabled · New checkout rollout",
          }}
        >
          new-checkout-flow
        </EvidenceHoverCard>
      </div>
      <div className="rounded-md border border-(--gray-a5) bg-(--color-panel-solid)">
        <EvidenceHoverCard
          target={{ kind: "ticket", id: "conv_88" }}
          clickable={true}
          preview={null}
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
          "The [coupon → purchase conversion](evidence:insight/9pQx3) dropped",
          "41% → 28% on Jan 3, the same day",
          "[a TypeError in CouponValidator](evidence:error/018f44aa) first",
          "appeared, and [14 recordings](evidence:replay/s_01HQ4K) show users",
          "retrying the field before leaving. This area is gated by",
          "[new-checkout-flow](evidence:flag/42).",
        ].join(" ")}
      />
    </div>
  ),
};

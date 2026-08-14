import { EvidenceRefChip } from "@posthog/ui/features/editor/components/EvidenceRefChip";
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
      <EvidenceRefChip target={{ kind: "error", id: "018f44aa-9c2b" }}>
        CouponValidator TypeError
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "replay", id: "s_01HQ4K" }}>
        14 rageclick recordings
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "flag", id: "new-checkout-flow" }}>
        new-checkout-flow
      </EvidenceRefChip>
      <EvidenceRefChip target={{ kind: "experiment", id: "exp_42" }}>
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
      <EvidenceRefChip target={{ kind: "something-new", id: "x1" }}>
        Unknown kind falls back
      </EvidenceRefChip>
    </div>
  ),
};

export const Clickable: Story = {
  render: () => (
    <div className="max-w-md text-[13px]">
      <EvidenceRefChip
        target={{
          kind: "insight",
          id: "9pQx3",
          url: "https://us.posthog.com/project/2/insights/9pQx3",
          value: "28.1%",
          desc: "coupon → purchase conversion, down 12.9pts since Jan 3",
        }}
      >
        Checkout funnel
      </EvidenceRefChip>
    </div>
  ),
};

export const WithSparkline: Story = {
  render: () => (
    <div className="max-w-md text-[13px]">
      <EvidenceRefChip
        target={{
          kind: "insight",
          id: "9pQx3",
          url: "https://us.posthog.com/project/2/insights/9pQx3",
          value: "28.1%",
          desc: "down 12.9pts since Jan 3",
          series: [41.2, 40.8, 41, 39.9, 40.4, 41.1, 28.4, 27.9, 28.1],
        }}
      >
        Checkout funnel
      </EvidenceRefChip>
    </div>
  ),
};

export const InsideAgentMessage: Story = {
  render: () => (
    <div className="max-w-xl">
      <MarkdownRenderer
        content={[
          "The [coupon → purchase conversion](evidence:insight/9pQx3?value=28.1%25&desc=down+12.9pts+since+Jan+3) dropped",
          "41% → 28% on Jan 3, the same day",
          "[a TypeError in CouponValidator](evidence:error/018f44aa?value=1%2C247+users&desc=first+seen+Jan+3%2C+spiking) first",
          "appeared, and [14 recordings](evidence:replay/s_01HQ4K?desc=users+retry+3%E2%80%935%C3%97+then+leave) show users",
          "retrying the field before leaving. This area is gated by",
          "[new-checkout-flow](evidence:flag/new-checkout-flow?url=https%3A%2F%2Fus.posthog.com%2Fproject%2F2%2Ffeature_flags%2F42&value=100%25&desc=all+users+since+Dec+12).",
        ].join(" ")}
      />
    </div>
  ),
};

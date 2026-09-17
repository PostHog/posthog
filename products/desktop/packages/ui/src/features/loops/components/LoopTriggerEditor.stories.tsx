import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import type { LoopTriggerDraft } from "../loopFormTypes";
import { LoopTriggerEditor } from "./LoopTriggerEditor";

function Harness({ initial }: { initial: LoopTriggerDraft[] }) {
  const [triggers, setTriggers] = useState(initial);
  return (
    <div className="w-[600px] p-4">
      <LoopTriggerEditor triggers={triggers} onChange={setTriggers} />
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Loops/LoopTriggerEditor",
  component: Harness,
};
export default meta;
type Story = StoryObj<typeof Harness>;

const gh = (config: object): LoopTriggerDraft[] => [
  {
    key: "t1",
    type: "github",
    enabled: true,
    config: {
      github_integration_id: 7,
      repository: "posthog/posthog",
      events: ["pull_request"],
      ...config,
    },
  },
];

export const ReviewRequestedFromTeam: Story = {
  args: {
    initial: gh({
      filters: { actions: ["review_requested"] },
    }),
  },
};

export const NoFiltersYet: Story = { args: { initial: gh({}) } };

export const TwoEventsShareFewerActions: Story = {
  args: { initial: gh({ events: ["pull_request", "issues"] }) },
};

export const PushHasNoActions: Story = {
  args: { initial: gh({ events: ["push"] }) },
};

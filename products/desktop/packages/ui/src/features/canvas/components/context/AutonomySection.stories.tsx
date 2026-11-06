import type { AutonomyLevel } from "@posthog/core/canvas/contextDocument";
import { AutonomySection } from "@posthog/ui/features/canvas/components/context/AutonomySection";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

const meta: Meta = {
  title: "Canvas/Spaces/Autonomy section",
  parameters: { layout: "padded" },
};

export default meta;

export const Default: StoryObj = {
  render: () => {
    const [level, setLevel] = useState<AutonomyLevel>("propose");
    return (
      <div className="max-w-lg">
        <AutonomySection value={level} onChange={setLevel} />
      </div>
    );
  },
};

export const Saving: StoryObj = {
  render: () => (
    <div className="max-w-lg">
      <AutonomySection value="ship_drafts" disabled onChange={() => {}} />
    </div>
  ),
};

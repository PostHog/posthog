import {
  emptySpaceSetupDraft,
  type SpaceSetupDraft,
} from "@posthog/core/canvas/spaceSetup";
import { SpaceFeatureFields } from "@posthog/ui/features/canvas/components/spaceSetup/SpaceFeatureFields";
import { SpaceGoalFields } from "@posthog/ui/features/canvas/components/spaceSetup/SpaceGoalFields";
import { SpaceSetupChoiceField } from "@posthog/ui/features/canvas/components/spaceSetup/SpaceSetupChoiceField";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

const meta: Meta = {
  title: "Canvas/Spaces/Space setup fields",
  parameters: { layout: "padded" },
};

export default meta;

function Frame({ children }: { children: React.ReactNode }) {
  return <div className="flex max-w-lg flex-col gap-4">{children}</div>;
}

export const Choice: StoryObj = {
  render: () => {
    const [draft, setDraft] = useState<SpaceSetupDraft>(emptySpaceSetupDraft);
    return (
      <Frame>
        <SpaceSetupChoiceField
          value={draft.choice}
          onChange={(choice) => setDraft({ ...draft, choice })}
        />
      </Frame>
    );
  },
};

export const Goal: StoryObj = {
  render: () => {
    const [draft, setDraft] = useState<SpaceSetupDraft>(() => ({
      ...emptySpaceSetupDraft(),
      choice: "goal",
      goal: {
        statement: "Increase the weekly activation rate of new desktop users",
        target: "20%",
        direction: "at_least",
        period: "week",
        deadline: "",
      },
    }));
    return (
      <Frame>
        <SpaceGoalFields
          value={draft.goal}
          onChange={(goal) => setDraft({ ...draft, goal })}
        />
      </Frame>
    );
  },
};

export const Feature: StoryObj = {
  render: () => {
    const [draft, setDraft] = useState<SpaceSetupDraft>(() => ({
      ...emptySpaceSetupDraft(),
      choice: "feature",
    }));
    return (
      <Frame>
        <SpaceFeatureFields
          value={draft.feature}
          onChange={(feature) => setDraft({ ...draft, feature })}
        />
      </Frame>
    );
  },
};

export const Disabled: StoryObj = {
  render: () => (
    <Frame>
      <SpaceSetupChoiceField value="goal" disabled onChange={() => {}} />
      <SpaceGoalFields
        value={emptySpaceSetupDraft().goal}
        disabled
        onChange={() => {}}
      />
    </Frame>
  ),
};

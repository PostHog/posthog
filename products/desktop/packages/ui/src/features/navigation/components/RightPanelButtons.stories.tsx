import { RightPanelButtons } from "@posthog/ui/features/navigation/components/RightPanelButtons";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta: Meta<typeof RightPanelButtons> = {
  title: "Navigation/RightPanelButtons",
  component: RightPanelButtons,
  parameters: { layout: "padded" },
  args: { taskId: "task-1", active: "timeline", hasNewArtifacts: false },
};

export default meta;
type Story = StoryObj<typeof RightPanelButtons>;

export const Resting: Story = {};

/** An artifact has landed since this session's panel last showed them. */
export const NewArtifacts: Story = {
  args: { hasNewArtifacts: true },
};

export const NewArtifactsWhileOnAnotherPanel: Story = {
  args: { hasNewArtifacts: true, active: "comments" },
};

/** What a reader sees the first time a run hands them a file. */
export const TeachingTheArtifactsPanel: Story = {
  args: { hasNewArtifacts: true, offerArtifactsTip: true },
};

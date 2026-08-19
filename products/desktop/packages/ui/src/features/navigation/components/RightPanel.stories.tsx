import { ExpandedPanelDrawer } from "@posthog/ui/features/navigation/components/RightPanel";
import type { Meta, StoryObj } from "@storybook/react-vite";

/**
 * The expanded panel's drawer. Its body is a session's own list, which fetches
 * through tRPC and so stays empty here - what these stories are for is the
 * drawer itself: how much of the window it takes, its title row and switcher,
 * and the resize handle on its inner edge.
 */
const meta: Meta<typeof ExpandedPanelDrawer> = {
  title: "Navigation/ExpandedPanelDrawer",
  component: ExpandedPanelDrawer,
  parameters: { layout: "fullscreen" },
  args: {
    taskId: "task-1",
    task: null,
    side: "changes",
    active: "changes",
    hasNewArtifacts: false,
    onCollapse: () => {},
  },
};

export default meta;
type Story = StoryObj<typeof ExpandedPanelDrawer>;

export const Changes: Story = {};

export const Timeline: Story = {
  args: { side: "timeline", active: "timeline" },
};

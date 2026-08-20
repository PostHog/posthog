import { RightPanelSurface } from "@posthog/ui/features/navigation/components/RightPanel";
import type { Meta, StoryObj } from "@storybook/react-vite";

/**
 * The panel's two layers over a stand-in content pane. What these stories are
 * for is where the pane stops moving: below the push share the pane gives way,
 * and above it the pane is parked and the panel covers it instead.
 */
const meta: Meta<typeof RightPanelSurface> = {
  title: "Navigation/RightPanelSurface",
  component: RightPanelSurface,
  parameters: { layout: "fullscreen" },
  args: {
    panelRef: { current: null },
    open: true,
    expanded: false,
    width: 340,
    isResizing: false,
    children: (
      <div className="flex h-[32px] shrink-0 items-center border-border border-b pl-3 font-medium text-[13px]">
        Changes
      </div>
    ),
  },
  render: (args) => (
    <div className="relative isolate flex h-screen overflow-hidden">
      <div className="min-w-0 flex-1 bg-fill-hover p-3 text-[13px]">
        The content pane, which the panel pushes over until it stops.
      </div>
      <RightPanelSurface {...args} />
    </div>
  ),
};

export default meta;
type Story = StoryObj<typeof RightPanelSurface>;

/** Under the push share: the pane gives up exactly the panel's width. */
export const Pushing: Story = {};

/** Over it: the pane is parked and the panel widens across it. */
export const Covering: Story = {
  args: { width: 900 },
};

export const Expanded: Story = {
  args: { expanded: true },
};

export const Closed: Story = {
  args: { open: false },
};

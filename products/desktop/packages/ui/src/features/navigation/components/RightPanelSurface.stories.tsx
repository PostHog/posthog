import { RightPanelSurface } from "@posthog/ui/features/navigation/components/RightPanelSurface";
import { resolvePanelGeometry } from "@posthog/ui/features/navigation/rightPanelGeometry";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";

/**
 * The panel's two layers over a stand-in content pane. What these stories are
 * for is where the pane stops moving: below the push share the pane gives way,
 * and above it the pane is parked, the panel covers it, and what is left of it
 * dims. Clicking the dimmed pane hands it back.
 */
/** The stories render at this width, so the geometry has a row to measure against. */
const ROW_WIDTH = 1200;

const meta: Meta<typeof RightPanelSurface> = {
  title: "Navigation/RightPanelSurface",
  component: RightPanelSurface,
  parameters: { layout: "fullscreen" },
  args: {
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
  render: (args) => {
    const Demo = () => {
      const panelRef = useRef<HTMLDivElement>(null);
      const [width, setWidth] = useState(args.width);
      const [expanded, setExpanded] = useState(args.expanded);
      const geometry = resolvePanelGeometry({
        storedWidth: width,
        rowWidth: ROW_WIDTH,
        open: args.open,
        expanded,
      });
      return (
        <div className="relative isolate flex h-screen overflow-hidden">
          <div className="isolate min-w-0 flex-1 bg-fill-hover p-3 text-[13px]">
            The content pane, which the panel pushes over until it stops.
          </div>
          <RightPanelSurface
            {...args}
            panelRef={panelRef}
            width={width}
            expanded={expanded}
            geometry={geometry}
            onUncover={() => {
              setExpanded(false);
              setWidth(geometry.uncoveredWidth);
            }}
          />
        </div>
      );
    };
    return <Demo />;
  },
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

/** Dragged to the ceiling rather than expanded: the same full width. */
export const DraggedToFull: Story = {
  args: { width: 1150 },
};

export const Closed: Story = {
  args: { open: false },
};

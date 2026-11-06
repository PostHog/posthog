import type { GridPlacement } from "@posthog/core/canvas/gridLayoutSchemas";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { GridPlacementTile, type PlacementActions } from "./GridPlacementTile";

const PLACEMENT: GridPlacement = {
  id: "p1",
  status: "pending",
  x: 0,
  y: 0,
  w: 2,
  h: 2,
};

const actions: PlacementActions = {
  describe: async () => {},
  reset: () => {},
  remove: () => {},
  discuss: () => {},
};

// A drawn box sits on the grid at the size it was drawn, so the stories frame
// the tile the way the canvas does rather than letting it fill the page. The
// chrome mirrors the wrapper in GridCanvasView; keep the two in step, since
// these stories are what say the smallest box still fits its contents.
function Tile({
  height,
  placement,
}: {
  height: number;
  placement: GridPlacement;
}) {
  return (
    <div
      className="overflow-hidden rounded-(--radius-3) border border-(--gray-5) bg-(--color-panel-solid)"
      style={{ width: 320, height }}
    >
      <GridPlacementTile
        placement={placement}
        interactive
        patching={false}
        actions={actions}
      />
    </div>
  );
}

const meta = {
  title: "Canvas/GridPlacementTile",
  component: Tile,
} satisfies Meta<typeof Tile>;

export default meta;
type Story = StoryObj<typeof meta>;

/** A box waiting for its description, drawn two rows tall. */
export const Pending: Story = {
  args: { height: 200, placement: PLACEMENT },
};

/** The smallest box the grid draws: one column, one row. */
export const PendingSingleCell: Story = {
  args: { height: 96, placement: { ...PLACEMENT, w: 1, h: 1 } },
};

/** A fill that failed keeps the prompt and offers a retry. */
export const Failed: Story = {
  args: {
    height: 200,
    placement: {
      ...PLACEMENT,
      status: "failed",
      prompt: "Weekly signups by source",
    },
  },
};

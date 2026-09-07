import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";
import { QuarantinedRouteDialog } from "./QuarantinedRouteDialog";

const meta = {
  title: "Crash recovery/Quarantined route dialog",
  component: QuarantinedRouteDialog,
  parameters: {
    layout: "centered",
  },
  args: {
    open: true,
    canArchive: true,
    isArchiving: false,
    onOpenAnyway: fn(),
    onArchive: fn(),
    onDismiss: fn(),
  },
} satisfies Meta<typeof QuarantinedRouteDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Task: Story = {};

export const Archiving: Story = {
  args: { isArchiving: true },
};

/** A quarantined route that is not a task has nothing to archive. */
export const NotATask: Story = {
  args: { canArchive: false },
};

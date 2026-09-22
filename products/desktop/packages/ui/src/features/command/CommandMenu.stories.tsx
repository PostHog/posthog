import type { Meta, StoryObj } from "@storybook/react-vite";
import { CommandMenu } from "./CommandMenu";

// The palette renders open over an empty backdrop. Its data hooks resolve to
// empty in Storybook (no authenticated client), so the story is for the
// query-language chrome: the highlighted input, the filter catalog, and the
// suggestion sections as a query is typed.
const meta: Meta<typeof CommandMenu> = {
  title: "Command/CommandMenu",
  component: CommandMenu,
  parameters: { layout: "fullscreen" },
  args: { open: true, onOpenChange: () => {} },
};

export default meta;
type Story = StoryObj<typeof CommandMenu>;

export const Open: Story = {};

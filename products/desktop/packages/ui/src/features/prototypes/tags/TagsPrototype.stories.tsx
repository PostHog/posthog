import { TagsPrototype } from "@posthog/ui/features/prototypes/tags/TagsPrototype";
import type { Meta, StoryObj } from "@storybook/react-vite";

/**
 * Clickable prototype exploring "tags" as a replacement for spaces:
 * flat many-to-many tags with startup metadata (repos, context, agent
 * preset), a single global left nav, and a Linear-style Home view for
 * running many agents at once.
 *
 * Things to click:
 * - Home icon (top of sidebar) vs. tag rows in the sidebar
 * - Home filters ("Needs you", "Running") and the "By tag" grouping
 * - Any task row → opens the detail panel; add/remove tags there
 * - A tag view's composer or the "New task" button → starting a task
 *   shows the repos/context the tags contribute
 */
const meta = {
  title: "Prototypes/TagsPrototype",
  component: TagsPrototype,
  parameters: { layout: "fullscreen" },
} satisfies Meta<typeof TagsPrototype>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Prototype: Story = {
  render: () => (
    <div className="h-screen w-screen">
      <TagsPrototype />
    </div>
  ),
};

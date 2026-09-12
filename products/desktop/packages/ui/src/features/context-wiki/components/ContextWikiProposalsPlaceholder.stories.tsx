import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";
import { ContextWikiProposalsPlaceholder } from "./ContextWikiProposalsPlaceholder";

const meta = {
  title: "Features/Context wiki/Proposal states",
  component: ContextWikiProposalsPlaceholder,
  decorators: [
    (Story) => (
      <div className="flex h-[420px] w-full">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof ContextWikiProposalsPlaceholder>;

export default meta;
type Story = StoryObj<typeof meta>;
export const Empty: Story = { args: { state: "empty" } };
export const Unselected: Story = { args: { state: "unselected" } };
export const LoadError: Story = {
  args: { state: "error", onRetry: fn(), retrying: false },
};
export const Retrying: Story = {
  args: { state: "error", onRetry: fn(), retrying: true },
};

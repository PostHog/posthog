import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReadOnlySessionNotice } from "./ReadOnlySessionNotice";

const meta = {
  title: "Features/Pi sessions/ReadOnlySessionNotice",
  component: ReadOnlySessionNotice,
  decorators: [
    (Story) => (
      <div className="mx-auto w-full max-w-3xl p-4">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof ReadOnlySessionNotice>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {};

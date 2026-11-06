import type { Meta, StoryObj } from "@storybook/react-vite";
import { NotificationsSettings } from "./NotificationsSettings";

const meta: Meta<typeof NotificationsSettings> = {
  title: "Settings/NotificationsSettings",
  component: NotificationsSettings,
  decorators: [
    (Story) => (
      <div className="max-w-[640px] p-6">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof NotificationsSettings>;

export const Default: Story = {};

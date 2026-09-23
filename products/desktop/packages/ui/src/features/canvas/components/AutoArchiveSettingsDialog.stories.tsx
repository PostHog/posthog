import type { Meta, StoryObj } from "@storybook/react-vite";
import { AutoArchiveSettingsDialog } from "./AutoArchiveSettingsDialog";

const meta = {
  title: "Canvas/AutoArchiveSettingsDialog",
  component: AutoArchiveSettingsDialog,
  args: {
    channel: {
      id: "channel-1",
      name: "growth-engineering",
      channelType: "public",
      starred: true,
      repositories: [],
      createdBy: null,
      autoArchiveAfterDays: 7,
    },
    open: true,
    onOpenChange: () => {},
    onSave: async () => true,
    isSaving: false,
  },
} satisfies Meta<typeof AutoArchiveSettingsDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const SharedSpace: Story = {};

export const PersonalSpace: Story = {
  args: {
    channel: {
      ...meta.args.channel,
      name: "personal",
      channelType: "personal",
      autoArchiveAfterDays: null,
    },
  },
};

export const CustomThreshold: Story = {
  args: {
    channel: {
      ...meta.args.channel,
      autoArchiveAfterDays: 45,
    },
  },
};

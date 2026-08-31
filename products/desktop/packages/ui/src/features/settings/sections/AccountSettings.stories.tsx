import type { Meta, StoryObj } from "@storybook/react-vite";
import { AccountSettingsView } from "./AccountSettings";

const user = {
  uuid: "0192b3a4-5c6d-7e8f-9a0b-1c2d3e4f5a6b",
  email: "max@example.com",
  first_name: "Max",
  last_name: "Hedgehog",
};

const SAMPLE_PICTURE = `data:image/svg+xml;utf8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 144 144"><rect width="144" height="144" fill="#f54e00"/><circle cx="72" cy="56" r="28" fill="#fdfdfc"/><path d="M20 144c0-32 24-52 52-52s52 20 52 52z" fill="#fdfdfc"/></svg>',
)}`;

const meta: Meta<typeof AccountSettingsView> = {
  title: "Settings/AccountSettings",
  component: AccountSettingsView,
  args: {
    user,
    status: "found",
    checking: false,
    imageUrl: SAMPLE_PICTURE,
    accountUrl: "https://us.posthog.com/settings/user",
    onRefresh: () => {},
    onOpenGravatar: () => {},
  },
  decorators: [
    (Story) => (
      <div className="mx-auto my-8 max-w-[800px] px-6">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof AccountSettingsView>;

export const WithGravatar: Story = {};

export const NoGravatar: Story = {
  args: { status: "missing", imageUrl: undefined },
};

export const Checking: Story = {
  args: { status: "unknown", checking: true, imageUrl: undefined },
};

export const Refreshing: Story = {
  args: { checking: true },
};

export const EmailOnly: Story = {
  args: {
    status: "missing",
    imageUrl: undefined,
    user: { uuid: user.uuid, email: "sam.rivera@example.com" },
  },
};

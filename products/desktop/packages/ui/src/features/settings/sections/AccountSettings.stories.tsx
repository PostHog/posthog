import type { Meta, StoryObj } from "@storybook/react-vite";
import { AccountSettingsView } from "./AccountSettings";

const user = {
  uuid: "0192b3a4-5c6d-7e8f-9a0b-1c2d3e4f5a6b",
  email: "max@example.com",
  first_name: "Max",
  last_name: "Hedgehog",
};

// A plain SVG stands in for a Gravatar so the story never touches the network.
const SAMPLE_PICTURE = `data:image/svg+xml;utf8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 144 144"><rect width="144" height="144" fill="#f54e00"/><circle cx="72" cy="56" r="28" fill="#fdfdfc"/><path d="M20 144c0-32 24-52 52-52s52 20 52 52z" fill="#fdfdfc"/></svg>',
)}`;

const meta: Meta<typeof AccountSettingsView> = {
  title: "Settings/AccountSettings",
  component: AccountSettingsView,
  args: {
    user,
    status: "found",
    imageUrl: SAMPLE_PICTURE,
    accountUrl: "https://us.posthog.com/settings/user",
    onImageLoadingStatusChange: () => {},
    onRefresh: () => {},
    onOpenGravatar: () => {},
  },
  // Match the settings page content column so the card sizes realistically.
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

/** Gravatar has a picture for the email: it fills the avatar and the action reads "Change". */
export const WithGravatar: Story = {};

/** No Gravatar yet: initials in a dashed slot and an "Add" action. */
export const NoGravatar: Story = {
  args: { status: "missing", imageUrl: undefined },
};

/** Still hashing the email or waiting on Gravatar: refresh is disabled and spinning. */
export const Checking: Story = {
  args: { status: "checking", imageUrl: undefined },
};

/** A person with no name set falls back to initials from the email. */
export const EmailOnly: Story = {
  args: {
    status: "missing",
    imageUrl: undefined,
    user: { uuid: user.uuid, email: "sam.rivera@example.com" },
  },
};

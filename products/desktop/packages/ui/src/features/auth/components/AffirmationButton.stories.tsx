import type { Meta, StoryObj } from "@storybook/react-vite";
import { AffirmationButton } from "./AffirmationButton";

const meta = {
  title: "Auth/Affirmation button",
  component: AffirmationButton,
} satisfies Meta<typeof AffirmationButton>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    onOpenSupport: () => {},
  },
};

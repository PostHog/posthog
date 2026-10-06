import type { Meta, StoryObj } from "@storybook/react-vite";
import { ReportSourceSuggestionView } from "./ReportSourceSuggestion";

const meta: Meta<typeof ReportSourceSuggestionView> = {
  title: "Inbox/ReportSourceSuggestion",
  component: ReportSourceSuggestionView,
  decorators: [
    (Story) => (
      <div className="max-w-sm p-4">
        <Story />
      </div>
    ),
  ],
  args: {
    product: "logs",
    reason:
      "Logs from the checkout service could show whether the timeout starts at the payment provider.",
    actionLabel: "Set up logs",
    onOpen: () => {},
  },
};
export default meta;

type Story = StoryObj<typeof ReportSourceSuggestionView>;

export const Logs: Story = {};

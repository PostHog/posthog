import type { Meta, StoryObj } from "@storybook/react-vite";
import { inboxStoryReport } from "../inboxStoryFixtures";
import { RelevanceShortlist } from "./RelevanceShortlist";

const report = inboxStoryReport({
  id: "example-1",
  title: "Checkout fails when an address has no postal code",
  summary: "The address form rejects a valid address.",
  priority: "P1",
  implementation_pr_url: null,
  actionability: "immediately_actionable",
});
const meta = {
  title: "Inbox/Relevance shortlist",
  component: RelevanceShortlist,
  args: {
    reports: [
      report,
      inboxStoryReport({
        ...report,
        id: "example-2",
        title: "Choose how to handle expired invitations",
        priority: "P2",
        actionability: "requires_human_input",
      }),
    ],
    loading: false,
    failed: false,
    saving: false,
    lastSnoozed: null,
    onRetry: () => {},
    onShowQueue: () => {},
    onSnooze: () => {},
  },
} satisfies Meta<typeof RelevanceShortlist>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Default: Story = {};
export const Narrow: Story = {
  decorators: [
    (Story) => (
      <div className="w-[520px]">
        <Story />
      </div>
    ),
  ],
};
export const LoadError: Story = { args: { failed: true } };
export const Empty: Story = { args: { reports: [] } };
export const Snoozed: Story = { args: { lastSnoozed: report } };

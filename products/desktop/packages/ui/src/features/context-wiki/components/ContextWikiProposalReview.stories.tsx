import { ApiRequestError } from "@posthog/api-client/fetcher";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { fn } from "storybook/test";
import { ContextWikiProposalReview } from "./ContextWikiProposalReview";

const meta = {
  title: "Features/Context wiki/Suggested edit",
  component: ContextWikiProposalReview,
  decorators: [
    (Story) => (
      <div className="flex h-[640px] max-w-4xl">
        <Story />
      </div>
    ),
  ],
  args: {
    proposal: {
      id: "proposal-1",
      task_id: "task-1",
      path: "areas/release-guide.md",
      original_content:
        "---\nsummary: Release guidance.\nstatus: active\n---\n\n# Release guide\n\n## Current state\n\nAll releases use the same review process.\n\n## Direction\n\nKeep changes small.\n\n## Links\n\n[[index]]\n",
      content:
        "---\nsummary: Release guidance.\nstatus: active\n---\n\n# Release guide\n\n## Current state\n\nProduction releases require a user review. Test releases can use the automated checks.\n\n## Direction\n\nKeep changes small.\n\n## Links\n\n[[index]]\n",
      base_head: "a".repeat(40),
      created_at: "2026-09-11T10:00:00Z",
    },
    applying: false,
    applied: false,
    error: null,
    onApply: fn(),
  },
} satisfies Meta<typeof ContextWikiProposalReview>;

export default meta;
type Story = StoryObj<typeof meta>;
export const Review: Story = {};
export const Applying: Story = { args: { applying: true } };
export const Conflict: Story = {
  args: { error: new ApiRequestError(409, "Wiki changed") },
};

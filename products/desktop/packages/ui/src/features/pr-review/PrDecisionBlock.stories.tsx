import { useHostTRPC } from "@posthog/host-router/react";
import { PrDecisionBlock } from "@posthog/ui/features/pr-review/PrDecisionBlock";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useQueryClient } from "@tanstack/react-query";

const prUrl = "https://github.com/example/project/pull/42";

const meta = {
  title: "Inbox/Reports/PR decision",
  component: PrDecisionBlock,
  args: { prUrl },
  decorators: [
    (Story, context) => {
      const trpc = useHostTRPC();
      const queryClient = useQueryClient();
      queryClient.setQueryData(trpc.git.getPrInfoByUrl.queryKey({ prUrl }), {
        number: 42,
        title: "Fix the empty state",
        body: "Show the next step when no results match.",
        author: null,
        state: "open",
        merged: false,
        draft: context.parameters.draft ?? true,
        mergeable: true,
        mergeStateStatus: "clean",
        baseRefName: "main",
        headRefName: "fix-empty-state",
        additions: 8,
        deletions: 2,
        changedFiles: 1,
      });
      queryClient.setQueryData(trpc.git.getPrChecks.queryKey({ prUrl }), [
        {
          name: "Unit tests",
          bucket: context.parameters.failing ? "fail" : "pass",
          link: null,
          workflow: "Tests",
          description: null,
        },
      ]);
      return (
        <div className="w-full max-w-[900px]">
          <Story />
        </div>
      );
    },
  ],
} satisfies Meta<typeof PrDecisionBlock>;

export default meta;
type Story = StoryObj<typeof meta>;
export const Draft: Story = {};
export const DraftWithFailingChecks: Story = { parameters: { failing: true } };
export const Ready: Story = { parameters: { draft: false } };
export const ReadyWithFailingChecks: Story = {
  parameters: { draft: false, failing: true },
};

import { GithubRefChip } from "@posthog/ui/features/editor/components/GithubRefChip";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Editor/GithubRefChip",
  component: GithubRefChip,
  parameters: { layout: "padded" },
} satisfies Meta<typeof GithubRefChip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const LifecycleStates: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-3 text-[13px]">
      <GithubRefChip
        href="https://github.com/example-org/example-repo/pull/101"
        kind="pr"
        prDetails={{
          state: "open",
          merged: false,
          draft: false,
          title: "Add account settings",
          author: "octocat",
          ciStatus: "success",
          isLoading: false,
        }}
      >
        example-org/example-repo#101
      </GithubRefChip>
      <GithubRefChip
        href="https://github.com/example-org/example-repo/pull/102"
        kind="pr"
        prDetails={{
          state: "open",
          merged: false,
          draft: true,
          title: "Improve search filters",
          author: "hubot",
          ciStatus: "pending",
          isLoading: false,
        }}
      >
        example-org/example-repo#102
      </GithubRefChip>
      <GithubRefChip
        href="https://github.com/example-org/example-repo/pull/103"
        kind="pr"
        prDetails={{
          state: "closed",
          merged: false,
          draft: false,
          title: "Update billing copy",
          author: "monalisa",
          ciStatus: "failure",
          isLoading: false,
        }}
      >
        example-org/example-repo#103
      </GithubRefChip>
      <GithubRefChip
        href="https://github.com/example-org/example-repo/pull/104"
        kind="pr"
        prDetails={{
          state: "closed",
          merged: true,
          draft: false,
          title: "Fix the sign-up redirect",
          author: "octocat",
          ciStatus: "success",
          isLoading: false,
        }}
      >
        example-org/example-repo#104
      </GithubRefChip>
    </div>
  ),
};

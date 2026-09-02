import { GithubRefChip } from "@posthog/ui/features/editor/components/GithubRefChip";
import {
  PrRefChip,
  type PrRefDetails,
} from "@posthog/ui/features/editor/components/PrRefChip";
import type { Meta, StoryObj } from "@storybook/react-vite";

const meta = {
  title: "Editor/GithubRefChip",
  component: GithubRefChip,
  parameters: { layout: "padded" },
} satisfies Meta<typeof GithubRefChip>;

export default meta;
type Story = StoryObj<typeof meta>;

export const WithoutLiveDetails: Story = {
  render: () => (
    <div className="text-[13px]">
      <GithubRefChip
        href="https://github.com/example-org/example-repo/pull/101"
        kind="pr"
      >
        example-org/example-repo#101
      </GithubRefChip>
    </div>
  ),
};

const LIFECYCLE_CASES: { number: number; details: PrRefDetails }[] = [
  {
    number: 101,
    details: {
      state: "open",
      merged: false,
      draft: false,
      title: "Add account settings",
      author: "octocat",
      isLoading: false,
      ciStatus: "success",
      isCiLoading: false,
    },
  },
  {
    number: 102,
    details: {
      state: "open",
      merged: false,
      draft: true,
      title: "Improve search filters",
      author: "hubot",
      isLoading: false,
      ciStatus: "pending",
      isCiLoading: false,
    },
  },
  {
    number: 103,
    details: {
      state: "closed",
      merged: false,
      draft: false,
      title: "Update billing copy",
      author: "monalisa",
      isLoading: false,
      ciStatus: "failure",
      isCiLoading: false,
    },
  },
  {
    number: 104,
    details: {
      state: "closed",
      merged: true,
      draft: false,
      title: "Fix the sign-up redirect",
      author: "octocat",
      isLoading: false,
      ciStatus: "success",
      isCiLoading: false,
    },
  },
];

export const LifecycleStates: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-3 text-[13px]">
      {LIFECYCLE_CASES.map(({ number, details }) => (
        <PrRefChip
          key={number}
          href={`https://github.com/example-org/example-repo/pull/${number}`}
          details={details}
        >
          {`example-org/example-repo#${number}`}
        </PrRefChip>
      ))}
    </div>
  ),
};

export const LoadingDetails: Story = {
  render: () => (
    <div className="text-[13px]">
      <PrRefChip
        href="https://github.com/example-org/example-repo/pull/105"
        details={{
          state: null,
          merged: false,
          draft: false,
          title: null,
          author: null,
          isLoading: true,
          ciStatus: null,
          isCiLoading: true,
        }}
      >
        example-org/example-repo#105
      </PrRefChip>
    </div>
  ),
};

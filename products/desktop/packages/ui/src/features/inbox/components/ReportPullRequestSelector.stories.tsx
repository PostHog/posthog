import type { Meta, StoryObj } from "@storybook/react";
import { useState } from "react";
import { ReportPullRequestSelector } from "./ReportPullRequestSelector";

const meta: Meta<typeof ReportPullRequestSelector> = {
  title: "Inbox/ReportPullRequestSelector",
  component: ReportPullRequestSelector,
  args: {
    value: "https://github.com/example/app/pull/2",
    pullRequests: [
      {
        id: "merged",
        url: "https://github.com/example/app/pull/1",
        state: "merged",
        merged: true,
      },
      {
        id: "open",
        url: "https://github.com/example/app/pull/2",
        state: "open",
        merged: false,
      },
      {
        id: "closed",
        url: "https://github.com/example/app/pull/3",
        state: "closed",
        merged: false,
      },
    ],
  },
  render: function Preview(args) {
    const [value, setValue] = useState(args.value);
    return (
      <ReportPullRequestSelector
        {...args}
        value={value}
        onValueChange={(next) => {
          if (next) setValue(next);
        }}
      />
    );
  },
};
export default meta;
type Story = StoryObj<typeof ReportPullRequestSelector>;
export const Stack: Story = {};
export const Narrow: Story = {
  decorators: [
    (Story) => (
      <div className="w-64">
        <Story />
      </div>
    ),
  ],
};

import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { CommentComposer } from "./CommentComposer";

const meta = {
  title: "Sessions/CommentComposer",
  component: CommentComposer,
  parameters: { layout: "centered" },
  args: {
    value: "",
    members: [],
    placeholder: "Add a comment…",
    onValueChange: () => {},
    onSubmit: () => {},
  },
  render: function Composer(args) {
    const [value, setValue] = useState(args.value);
    return (
      <div className="w-80">
        <CommentComposer
          {...args}
          value={value}
          onValueChange={setValue}
          onSubmit={() => setValue("")}
        />
      </div>
    );
  },
} satisfies Meta<typeof CommentComposer>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Empty: Story = {};
export const WithText: Story = { args: { value: "Check the updated layout." } };

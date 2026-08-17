import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { ReportDiscussionStarterView } from "./CanvasSidePanel";

const suggestions = [
  "Investigate this further",
  "Explain the evidence",
  "What should happen next?",
];

function ReportDiscussionStarterStory({
  initialQuestion = "",
  isDiscussing = false,
}: {
  initialQuestion?: string;
  isDiscussing?: boolean;
}) {
  const [question, setQuestion] = useState(initialQuestion);

  return (
    <div className="h-[620px] w-[360px] border bg-gray-1">
      <ReportDiscussionStarterView
        question={question}
        isDiscussing={isDiscussing}
        suggestions={suggestions}
        onQuestionChange={setQuestion}
        onSubmit={() => {}}
      />
    </div>
  );
}

const meta: Meta<typeof ReportDiscussionStarterStory> = {
  title: "Canvas/Report discussion starter",
  component: ReportDiscussionStarterStory,
  decorators: [
    (Story) => (
      <div className="flex min-h-screen items-center justify-center p-8">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ReportDiscussionStarterStory>;

export const Blank: Story = {};

export const SuggestedQuestion: Story = {
  args: { initialQuestion: "Explain the evidence" },
};

export const Starting: Story = {
  args: {
    initialQuestion: "Investigate this further",
    isDiscussing: true,
  },
};

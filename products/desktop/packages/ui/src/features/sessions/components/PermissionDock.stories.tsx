import {
  buildQuestionOptions,
  buildQuestionToolCallData,
  type QuestionItem,
} from "@posthog/agent/adapters/claude/questions/utils";
import { PermissionSelector } from "@posthog/ui/features/permissions/PermissionSelector";
import { PermissionDock } from "@posthog/ui/features/sessions/components/PermissionDock";
import type { Meta, StoryObj } from "@storybook/react-vite";

const wordyQuestions: QuestionItem[] = [
  {
    question:
      "The migration can move the queue off Postgres in three different orders. Which one do you want?",
    header: "Approach",
    options: [
      {
        label: "Dual-write, then cut reads over",
        description:
          "Write every job to both stores, leave reads on Postgres until the new store has a full day of traffic, then flip reads in one deploy. Slowest, but every step is reversible on its own.",
      },
      {
        label: "Shadow the consumer first",
        description:
          "Stand up a second consumer that reads the new store and discards its results, compare its output against the live one for a week, then promote it. Catches ordering bugs before any user sees them.",
      },
      {
        label: "Cut over per queue",
        description:
          "Move one low-volume queue end to end, watch it for a day, then work up to the busiest one. Keeps the blast radius small but stretches the migration across several weeks.",
      },
      {
        label: "Freeze writes and copy",
        description:
          "Pause producers, drain the backlog, copy what is left, and restart against the new store. Fastest to finish and easiest to reason about, at the cost of a short window where jobs queue up in the producers.",
      },
      {
        label: "Leave it on Postgres",
        description:
          "Keep the queue where it is and spend the time on the indexes and the vacuum schedule instead. Worth considering if the current pain is throughput rather than storage.",
      },
    ],
  },
];

/** Stands in for the thread the dock must not swallow. */
function ChatColumn({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-[520px] flex-col overflow-hidden rounded-(--radius-3) border border-(--gray-6) bg-(--gray-2)">
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 text-[13px]">
        {Array.from({ length: 12 }, (_, i) => `step-${i + 1}`).map(
          (step, i) => (
            <p key={step} className="mb-2 text-(--gray-11)">
              Investigation step {i + 1}: read the consumer, traced the retry
              path, and confirmed the backlog builds only while the nightly job
              holds its advisory lock.
            </p>
          ),
        )}
      </div>
      {children}
    </div>
  );
}

const meta: Meta<typeof PermissionDock> = {
  title: "Components/Sessions/PermissionDock",
  component: PermissionDock,
  parameters: { layout: "padded" },
};

export default meta;
type Story = StoryObj<typeof PermissionDock>;

export const WordyQuestion: Story = {
  render: () => (
    <ChatColumn>
      <PermissionDock compact={false}>
        <PermissionSelector
          toolCall={buildQuestionToolCallData(wordyQuestions)}
          options={buildQuestionOptions(wordyQuestions[0])}
          onSelect={() => {}}
          onCancel={() => {}}
        />
      </PermissionDock>
    </ChatColumn>
  ),
};

import type {
  PermissionOption,
  SessionConfigOption,
} from "@agentclientprotocol/sdk";
import {
  buildQuestionOptions,
  buildQuestionToolCallData,
  type QuestionItem,
} from "@posthog/agent/adapters/claude/questions/utils";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import type { PermissionToolCall } from "@posthog/ui/features/permissions/types";
import { ComposerCard } from "@posthog/ui/features/sessions/components/ComposerCard";
import {
  ComposerPanelReopenChip,
  ComposerPermissionPanel,
} from "@posthog/ui/features/sessions/components/ComposerPermissionPanel";
import { ComposerWidth } from "@posthog/ui/features/sessions/components/ComposerWidth";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

// The host tRPC, DI, and query providers come from the `withAppProviders`
// decorator in `.storybook/preview.tsx`.

const modeOption = {
  id: "mode",
  name: "Mode",
  type: "select" as const,
  currentValue: "auto",
  options: [
    { value: "read-only", name: "Read-only" },
    { value: "auto", name: "Auto" },
    { value: "full-access", name: "Full access" },
  ],
} satisfies SessionConfigOption;

const PLAN_OPTIONS: PermissionOption[] = [
  { kind: "allow_always", name: 'Yes, and use "auto" mode', optionId: "auto" },
  {
    kind: "allow_always",
    name: "Yes, and auto-accept edits",
    optionId: "acceptEdits",
  },
  {
    kind: "allow_once",
    name: "Yes, and manually approve edits",
    optionId: "default",
  },
  {
    kind: "reject_once",
    name: "No, and tell the agent what to do differently",
    optionId: "reject_with_feedback",
    _meta: { customInput: true },
  },
];

const SHORT_PLAN = `## Move the composer controls into a card

1. Wrap the input and the controls above it in one card.
2. Dock the plan in that card while it waits for an answer.
3. Fold the toolbar away for as long as the plan is open.`;

const LONG_PLAN = `## Rework the queue store

${Array.from(
  { length: 14 },
  (_, i) =>
    `${i + 1}. Step ${i + 1}: read the consumer, keep the retry path, and cover the new branch with a test that fails without it.`,
).join("\n")}

### Risks

- The store is read on every keystroke, so a wider selector re-renders the composer.
- A reload must find the same answer still pending.`;

function planToolCall(plan: string): PermissionToolCall {
  return {
    toolCallId: `plan-${plan.length}`,
    title: "Approve this plan to proceed?",
    kind: "switch_mode",
    rawInput: { plan },
  } as PermissionToolCall;
}

const ONE_QUESTION: QuestionItem[] = [
  {
    question: "Where should the collapsed state live?",
    header: "Storage",
    options: [
      {
        label: "Per tool call, persisted",
        description:
          "The panel reopens closed after a reload, for as long as the same answer is still due.",
      },
      {
        label: "Per session, in memory",
        description: "Simpler, but a reload reopens every panel.",
      },
    ],
  },
];

const THREE_QUESTIONS: QuestionItem[] = [
  ONE_QUESTION[0],
  {
    question:
      "What should the card do when the plan is longer than the column?",
    header: "Overflow",
    options: [
      {
        label: "Scroll the plan",
        description:
          "The card stops at the top of the thread and the plan scrolls.",
      },
      {
        label: "Clip the plan",
        description: "Cheaper, but the end is unreachable.",
      },
    ],
  },
  {
    question: "Which controls should come back when the panel closes?",
    header: "Controls",
    options: [
      {
        label: "All of them",
        description:
          "The composer reads the same as it did before the plan arrived.",
      },
      {
        label: "Send only",
        description: "Keeps the answer the obvious next action.",
      },
    ],
  },
];

function questionToolCall(questions: QuestionItem[]): PermissionToolCall {
  return buildQuestionToolCallData(questions) as PermissionToolCall;
}

/** Stands in for the thread the card must not swallow. */
function ChatColumn({
  height,
  dimmed,
  onOverlayClick,
  children,
}: {
  height: number;
  dimmed: boolean;
  onOverlayClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="relative flex flex-col overflow-hidden rounded-md border border-border bg-background"
      style={{ height }}
    >
      {/* Mirrors the session column: the thread group is what gives way when
          the card grows, and what the overlay covers. */}
      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 text-xs">
          {Array.from({ length: 12 }, (_, i) => `step-${i + 1}`).map(
            (step, i) => (
              <p key={step} className="mb-2 text-muted-foreground">
                Investigation step {i + 1}: read the consumer, traced the retry
                path, and confirmed the backlog builds only while the nightly
                job holds its lock.
              </p>
            ),
          )}
        </div>
        {dimmed && (
          <div
            aria-hidden="true"
            onClick={onOverlayClick}
            className="absolute inset-0 bg-background/60"
          />
        )}
      </div>
      <div className="flex max-h-full shrink-0 flex-col">{children}</div>
    </div>
  );
}

interface HarnessProps {
  sessionId: string;
  /** Absent renders the card as it looks with nothing waiting on the user. */
  permission?: { toolCall: PermissionToolCall; options: PermissionOption[] };
  startCollapsed?: boolean;
  columnHeight?: number;
}

function ComposerCardHarness({
  sessionId,
  permission,
  startCollapsed = false,
  columnHeight = 520,
}: HarnessProps) {
  const [collapsed, setCollapsed] = useState(startCollapsed);
  const [mode, setMode] = useState<SessionConfigOption>(modeOption);
  const isOpen = !!permission && !collapsed;

  return (
    <ChatColumn
      height={columnHeight}
      dimmed={isOpen}
      onOverlayClick={() => setCollapsed(true)}
    >
      <ComposerWidth compact={false} fill>
        <ComposerCard
          panel={
            isOpen && permission ? (
              <ComposerPermissionPanel
                toolCall={permission.toolCall}
                options={permission.options}
                onSelect={() => setCollapsed(true)}
                onCancel={() => setCollapsed(true)}
                onClose={() => setCollapsed(true)}
              />
            ) : undefined
          }
          controlsEnd={
            permission && collapsed ? (
              <ComposerPanelReopenChip
                toolCall={permission.toolCall}
                onOpen={() => setCollapsed(false)}
              />
            ) : undefined
          }
        >
          <PromptInput
            sessionId={sessionId}
            placeholder="Type a message... ! for bash mode, / for skills"
            modeOption={mode}
            onModeChange={(value) =>
              setMode({ ...modeOption, currentValue: value })
            }
            modelSelector={null}
            toolbarCollapsed={isOpen}
            onSubmit={() => {}}
          />
        </ComposerCard>
      </ComposerWidth>
    </ChatColumn>
  );
}

const meta: Meta<typeof ComposerCardHarness> = {
  title: "Components/Sessions/ComposerCard",
  component: ComposerCardHarness,
  parameters: { layout: "padded" },
  decorators: [
    (Story) => (
      <div className="max-w-[800px]">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof ComposerCardHarness>;

export const Idle: Story = {
  name: "Nothing waiting",
  args: { sessionId: "sb-card-idle" },
};

export const PlanOpen: Story = {
  name: "Plan: open",
  args: {
    sessionId: "sb-card-plan",
    permission: { toolCall: planToolCall(SHORT_PLAN), options: PLAN_OPTIONS },
  },
};

export const PlanClosed: Story = {
  name: "Plan: closed, reopen chip",
  args: {
    sessionId: "sb-card-plan-closed",
    permission: { toolCall: planToolCall(SHORT_PLAN), options: PLAN_OPTIONS },
    startCollapsed: true,
  },
};

export const LongPlanOpen: Story = {
  name: "Plan: taller than the column",
  args: {
    sessionId: "sb-card-plan-long",
    permission: { toolCall: planToolCall(LONG_PLAN), options: PLAN_OPTIONS },
  },
};

export const OneChoiceOpen: Story = {
  name: "Choices: one question",
  args: {
    sessionId: "sb-card-choice",
    permission: {
      toolCall: questionToolCall(ONE_QUESTION),
      options: buildQuestionOptions(ONE_QUESTION[0]),
    },
  },
};

export const ManyChoicesOpen: Story = {
  name: "Choices: three questions",
  args: {
    sessionId: "sb-card-choices",
    permission: {
      toolCall: questionToolCall(THREE_QUESTIONS),
      options: buildQuestionOptions(THREE_QUESTIONS[0]),
    },
  },
};

export const ChoicesClosed: Story = {
  name: "Choices: closed, reopen chip",
  args: {
    sessionId: "sb-card-choices-closed",
    permission: {
      toolCall: questionToolCall(THREE_QUESTIONS),
      options: buildQuestionOptions(THREE_QUESTIONS[0]),
    },
    startCollapsed: true,
  },
};

const MATRIX: Array<{ label: string; args: Omit<HarnessProps, "sessionId"> }> =
  [
    { label: "Nothing waiting", args: {} },
    {
      label: "Plan open",
      args: {
        permission: {
          toolCall: planToolCall(SHORT_PLAN),
          options: PLAN_OPTIONS,
        },
      },
    },
    {
      label: "Plan closed",
      args: {
        permission: {
          toolCall: planToolCall(SHORT_PLAN),
          options: PLAN_OPTIONS,
        },
        startCollapsed: true,
      },
    },
    {
      label: "Plan taller than the column",
      args: {
        permission: {
          toolCall: planToolCall(LONG_PLAN),
          options: PLAN_OPTIONS,
        },
      },
    },
    {
      label: "One question",
      args: {
        permission: {
          toolCall: questionToolCall(ONE_QUESTION),
          options: buildQuestionOptions(ONE_QUESTION[0]),
        },
      },
    },
    {
      label: "Three questions",
      args: {
        permission: {
          toolCall: questionToolCall(THREE_QUESTIONS),
          options: buildQuestionOptions(THREE_QUESTIONS[0]),
        },
      },
    },
    {
      label: "Questions closed",
      args: {
        permission: {
          toolCall: questionToolCall(THREE_QUESTIONS),
          options: buildQuestionOptions(THREE_QUESTIONS[0]),
        },
        startCollapsed: true,
      },
    },
  ];

export const Matrix: Story = {
  name: "Matrix (every state on one page)",
  parameters: { layout: "fullscreen" },
  decorators: [
    (Story) => (
      <div className="p-4">
        <Story />
      </div>
    ),
  ],
  render: () => (
    <div className="flex flex-col gap-6">
      {MATRIX.map((variant, index) => (
        <div key={variant.label} className="flex flex-col gap-1">
          <span className="font-medium text-muted-foreground text-xs">
            {variant.label}
          </span>
          <div className="max-w-[800px]">
            <ComposerCardHarness
              {...variant.args}
              columnHeight={360}
              sessionId={`sb-card-matrix-${index}`}
            />
          </div>
        </div>
      ))}
    </div>
  ),
};

import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import type { FileAttachment } from "@posthog/core/message-editor/content";
import type { ContextUsage } from "@posthog/core/sessions/contextUsage";
import { PromptHistoryDialog } from "@posthog/ui/features/message-editor/components/PromptHistoryDialog";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import type { MentionChip } from "@posthog/ui/features/message-editor/content";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { ContextUsageIndicator } from "@posthog/ui/features/sessions/components/ContextUsageIndicator";
import { ReasoningLevelSelector } from "@posthog/ui/features/sessions/components/ReasoningLevelSelector";
import { SteerQueueToggle } from "@posthog/ui/features/sessions/components/SteerQueueToggle";
import { ChannelContextChip } from "@posthog/ui/features/task-detail/components/ChannelContextChip";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useRef, useState } from "react";

// The host tRPC, DI, and query providers are supplied globally by the
// `withAppProviders` decorator in `.storybook/preview.tsx`. Image attachments
// read their thumbnail through the host, which never answers here, so they
// render the extension face rather than a picture.

// --- Mock data matching SessionConfigOption shape ---

const mockModelOption = {
  id: "model",
  name: "Model",
  type: "select" as const,
  currentValue: "gpt-5.5",
  options: [
    {
      group: "recommended",
      name: "Recommended",
      options: [
        { value: "gpt-5.5", name: "gpt-5.5" },
        { value: "claude-opus-5", name: "Claude Opus 5" },
        { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
        { value: "claude-sonnet-4-6", name: "Claude Sonnet 4.6" },
      ],
    },
    {
      group: "other",
      name: "Other",
      options: [
        { value: "claude-opus-4-8", name: "Claude Opus 4.8" },
        { value: "o3-pro", name: "o3-pro" },
      ],
    },
  ],
} satisfies SessionConfigOption;

const mockReasoningOption = {
  id: "thought",
  name: "Reasoning",
  type: "select" as const,
  currentValue: "high",
  options: [
    { value: "off", name: "Off" },
    { value: "low", name: "Low" },
    { value: "medium", name: "Medium" },
    { value: "high", name: "High" },
  ],
} satisfies SessionConfigOption;

const mockModeOption = {
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

const mockUsage: ContextUsage = {
  used: 24_000,
  size: 353_000,
  percentage: 7,
  cost: { amount: 0.42, currency: "USD" },
  breakdown: {
    systemPrompt: 14_000,
    tools: 0,
    rules: 0,
    skills: 0,
    mcp: 0,
    subagents: 0,
    conversation: 11_000,
  },
};

const nearFullUsage: ContextUsage = {
  ...mockUsage,
  used: 320_000,
  percentage: 91,
  breakdown: {
    systemPrompt: 14_000,
    tools: 22_000,
    rules: 8000,
    skills: 6000,
    mcp: 12_000,
    subagents: 18_000,
    conversation: 240_000,
  },
};

function attachment(label: string, id = `/tmp/${label}`): FileAttachment {
  return { id, label };
}

const SAMPLE_TEXT = "Rework the composer toolbar so it sits under the input";
const LONG_TEXT = Array.from(
  { length: 12 },
  (_, i) => `Line ${i + 1}: keep the composer scrolling past its max height.`,
).join("\n");

// --- Harness: fills the editor and mounts the optional toolbar slots ---

interface HarnessProps
  extends Omit<React.ComponentProps<typeof PromptInput>, "sessionId"> {
  sessionId?: string;
  /** Seeded into the editor after mount, so `!` reaches bash mode. */
  text?: string;
  chips?: MentionChip[];
  attachments?: FileAttachment[];
  /** The merged model + effort pill a live session renders. */
  showSelectors?: boolean;
  showMode?: boolean;
  showHistory?: boolean;
  showSteerQueue?: boolean;
  contextUsage?: ContextUsage | null;
  channelContext?: boolean;
}

function PromptInputHarness({
  sessionId = "storybook-session",
  text,
  chips,
  attachments,
  showSelectors = true,
  showMode = true,
  showHistory = true,
  showSteerQueue = true,
  contextUsage = mockUsage,
  channelContext = false,
  ...props
}: HarnessProps) {
  const ref = useRef<EditorHandle>(null);
  const seededRef = useRef(false);
  const [reasoningOption, setReasoningOption] =
    useState<SessionConfigOption>(mockReasoningOption);
  const [modeOption, setModeOption] =
    useState<SessionConfigOption>(mockModeOption);

  // One pass after mount: the editor is ready a tick late, and re-seeding on
  // every render would fight whatever is typed into it.
  useEffect(() => {
    if (seededRef.current) return;
    seededRef.current = true;
    const timer = setTimeout(() => {
      if (text) ref.current?.setContent(text);
      for (const chip of chips ?? []) ref.current?.insertChip(chip);
      for (const file of attachments ?? []) ref.current?.addAttachment(file);
    }, 200);
    return () => clearTimeout(timer);
  }, [text, chips, attachments]);

  return (
    <PromptInput
      ref={ref}
      sessionId={sessionId}
      modeOption={showMode ? modeOption : undefined}
      onModeChange={
        showMode
          ? (value) => setModeOption({ ...mockModeOption, currentValue: value })
          : undefined
      }
      allowBypassPermissions
      modelSelector={null}
      reasoningSelector={
        showSelectors ? (
          <ReasoningLevelSelector
            thoughtOption={reasoningOption}
            modelOption={mockModelOption}
            adapter="claude"
            onChange={(value) =>
              setReasoningOption({
                ...mockReasoningOption,
                currentValue: value,
              })
            }
          />
        ) : null
      }
      historyButton={
        showHistory ? (
          <PromptHistoryDialog
            onSelect={() => {}}
            hasPendingDraft={() => false}
          />
        ) : undefined
      }
      messagingModeToggle={
        showSteerQueue ? (
          <SteerQueueToggle taskId="storybook-task" />
        ) : undefined
      }
      toolbarEndSlot={
        contextUsage ? (
          <ContextUsageIndicator usage={contextUsage} />
        ) : undefined
      }
      submitAdornment={
        channelContext ? (
          <ChannelContextChip channelName="engineering" onRemove={() => {}} />
        ) : undefined
      }
      {...props}
    />
  );
}

const meta: Meta<typeof PromptInputHarness> = {
  title: "Features/MessageEditor/PromptInput",
  component: PromptInputHarness,
  parameters: {
    layout: "padded",
  },
  decorators: [
    (Story) => (
      <div className="max-w-[800px]">
        <Story />
      </div>
    ),
  ],
  args: {
    placeholder: "Type a message...",
    disabled: false,
    isLoading: false,
    autoFocus: false,
    isActiveSession: true,
    enableBashMode: true,
    enableCommands: true,
    showSelectors: true,
    showMode: true,
    showHistory: true,
    showSteerQueue: true,
    onSubmit: () => {},
    onCancel: () => {},
  },
  argTypes: {
    disabled: { control: "boolean" },
    isLoading: { control: "boolean" },
    enableBashMode: { control: "boolean" },
    enableCommands: { control: "boolean" },
    showSelectors: { control: "boolean" },
    showMode: { control: "boolean" },
    showHistory: { control: "boolean" },
    showSteerQueue: { control: "boolean" },
    channelContext: { control: "boolean" },
    hideDefaultToolbar: { control: "boolean" },
    editorHeight: { control: "radio", options: ["default", "large"] },
    placeholder: { control: "text" },
  },
};

export default meta;
type Story = StoryObj<typeof PromptInputHarness>;

// --- Content states ---

export const Empty: Story = {
  args: { sessionId: "sb-empty" },
};

export const Filled: Story = {
  args: { sessionId: "sb-filled", text: SAMPLE_TEXT },
};

export const Overflowing: Story = {
  name: "Filled (scrolls past max height)",
  args: { sessionId: "sb-overflow", text: LONG_TEXT },
};

export const LargeEditor: Story = {
  name: "Filled (editorHeight large)",
  args: { sessionId: "sb-large", text: LONG_TEXT, editorHeight: "large" },
};

// --- Chips ---

export const WithFileChip: Story = {
  name: "Chip: file",
  args: {
    sessionId: "sb-chip-file",
    chips: [
      {
        type: "file",
        id: "/src/settings.json",
        label: ".claude/settings.json",
      },
    ],
  },
};

export const WithCommandChip: Story = {
  name: "Chip: command",
  args: {
    sessionId: "sb-chip-command",
    chips: [{ type: "command", id: "good", label: "good" }],
  },
};

export const WithMultipleChips: Story = {
  name: "Chips: several",
  args: {
    sessionId: "sb-chip-multi",
    chips: [
      {
        type: "file",
        id: "/src/settings.json",
        label: ".claude/settings.json",
      },
      { type: "command", id: "good", label: "good" },
      {
        type: "file",
        id: "/workflows/release.yml",
        label: "workflows/agent-release.yml",
      },
    ],
  },
};

export const AllChipTypes: Story = {
  name: "Chips: every type",
  args: {
    sessionId: "sb-chip-all",
    chips: [
      { type: "file", id: "/src/index.ts", label: "src/index.ts" },
      { type: "command", id: "review", label: "review" },
      {
        type: "github_issue",
        id: "https://github.com/org/repo/issues/123",
        label: "#123 Fix the bug",
      },
      {
        type: "github_pr",
        id: "https://github.com/org/repo/pull/456",
        label: "org/repo#456",
      },
      { type: "error", id: "error-1", label: "TypeError: undefined" },
      { type: "experiment", id: "exp-1", label: "new-checkout-flow" },
      { type: "insight", id: "insight-1", label: "Weekly active users" },
      { type: "feature_flag", id: "flag-1", label: "enable-dark-mode" },
      {
        type: "file",
        id: "/tmp/pasted-content.txt",
        label: "pasted-content.txt",
      },
    ],
  },
};

export const LongChipLabels: Story = {
  name: "Chips: long labels",
  args: {
    sessionId: "sb-chip-long",
    chips: [
      {
        type: "file",
        id: "/apps/code/src/renderer/features/message-editor/tiptap/MentionChipView.tsx",
        label:
          "apps/code/src/renderer/features/message-editor/tiptap/MentionChipView.tsx",
      },
      {
        type: "file",
        id: "/packages/agent/src/adapters/claude/permissions/permission-options.ts",
        label:
          "packages/agent/src/adapters/claude/permissions/permission-options.ts",
      },
    ],
  },
};

// --- Attachments ---

export const OneAttachment: Story = {
  name: "Attachments: one",
  args: {
    sessionId: "sb-attach-one",
    attachments: [attachment("diagram.png")],
  },
};

export const ManyAttachments: Story = {
  name: "Attachments: many kinds",
  args: {
    sessionId: "sb-attach-many",
    attachments: [
      attachment("screenshot.png"),
      attachment("recording.gif"),
      attachment("notes.md"),
      attachment("trace.json"),
      attachment("query.sql"),
      attachment("archive.tar.gz"),
      attachment("no-extension"),
    ],
  },
};

export const AttachmentsUploading: Story = {
  name: "Attachments: uploading and failed",
  args: {
    sessionId: "sb-attach-status",
    attachments: [
      attachment("uploading.png"),
      attachment("failed.png"),
      attachment("done.png"),
    ],
    attachmentUploadStatuses: {
      "/tmp/uploading.png": "uploading",
      "/tmp/failed.png": "error",
    },
  },
};

export const AttachmentsWithChannelContext: Story = {
  name: "Attachments: with channel CONTEXT.md",
  args: {
    sessionId: "sb-attach-context",
    channelContext: true,
    attachments: [attachment("screenshot.png"), attachment("notes.md")],
  },
};

export const ChannelContextOnly: Story = {
  name: "Attachments: channel CONTEXT.md only",
  args: { sessionId: "sb-context-only", channelContext: true },
};

export const AttachmentsAndChipsAndText: Story = {
  name: "Attachments + chips + text",
  args: {
    sessionId: "sb-everything",
    text: SAMPLE_TEXT,
    channelContext: true,
    attachments: [attachment("screenshot.png"), attachment("trace.json")],
    chips: [
      { type: "file", id: "/src/index.ts", label: "src/index.ts" },
      { type: "command", id: "review", label: "review" },
    ],
  },
};

// --- Bash mode ---

export const BashModeEmpty: Story = {
  name: "Bash mode: just the bang",
  args: { sessionId: "sb-bash-empty", text: "!" },
};

export const BashModeFilled: Story = {
  name: "Bash mode: with a command",
  args: { sessionId: "sb-bash-filled", text: "!git status --short" },
};

export const BashModeDisabled: Story = {
  name: "Bash mode: disabled (bang is plain text)",
  args: {
    sessionId: "sb-bash-off",
    enableBashMode: false,
    text: "!git status --short",
  },
};

// --- Run state ---

export const Loading: Story = {
  name: "Running (stop button)",
  args: { sessionId: "sb-loading", isLoading: true, text: SAMPLE_TEXT },
};

export const Disabled: Story = {
  args: { sessionId: "sb-disabled", disabled: true, text: SAMPLE_TEXT },
};

export const EditingQueued: Story = {
  name: "Editing a queued message",
  args: {
    sessionId: "sb-editing",
    text: SAMPLE_TEXT,
    isEditingQueued: true,
    onCancelEdit: () => {},
    submitTooltipOverride: "Save edit",
  },
};

export const SubmitBlocked: Story = {
  name: "Submit blocked externally",
  args: {
    sessionId: "sb-blocked",
    text: SAMPLE_TEXT,
    submitDisabledExternal: true,
  },
};

// --- Toolbar composition ---

export const NoSelectors: Story = {
  name: "Toolbar: no model or reasoning",
  args: { sessionId: "sb-no-selectors", showSelectors: false },
};

export const NoMode: Story = {
  name: "Toolbar: no mode",
  args: { sessionId: "sb-no-mode", showMode: false },
};

export const NoContextUsage: Story = {
  name: "Toolbar: no context ring",
  args: { sessionId: "sb-no-usage", contextUsage: null },
};

export const ContextNearlyFull: Story = {
  name: "Toolbar: context nearly full",
  args: { sessionId: "sb-usage-full", contextUsage: nearFullUsage },
};

export const ToolbarBare: Story = {
  name: "Toolbar: nothing but attach",
  args: {
    sessionId: "sb-bare",
    showSelectors: false,
    showMode: false,
    showHistory: false,
    showSteerQueue: false,
    contextUsage: null,
  },
};

export const NoToolbar: Story = {
  name: "Toolbar: hidden entirely",
  args: {
    sessionId: "sb-no-toolbar",
    hideDefaultToolbar: true,
    showHistory: false,
    showSteerQueue: false,
    contextUsage: null,
    text: SAMPLE_TEXT,
  },
};

export const WithHeaderAddon: Story = {
  name: "Header addon above the editor",
  args: {
    sessionId: "sb-header",
    text: SAMPLE_TEXT,
    headerAddon: (
      <span className="text-[12px] text-muted-foreground">
        Autoresearch armed — the next send iterates on its own
      </span>
    ),
  },
};

// --- The whole grid at once ---

const MATRIX: Array<{ label: string; args: Partial<HarnessProps> }> = [
  { label: "Empty", args: {} },
  { label: "Filled", args: { text: SAMPLE_TEXT } },
  { label: "Bash mode", args: { text: "!git status" } },
  {
    label: "Chips",
    args: { chips: [{ type: "file", id: "/a.ts", label: "a.ts" }] },
  },
  { label: "Attachment", args: { attachments: [attachment("shot.png")] } },
  {
    label: "Attachment + channel context",
    args: { channelContext: true, attachments: [attachment("shot.png")] },
  },
  {
    label: "Everything",
    args: {
      text: SAMPLE_TEXT,
      channelContext: true,
      attachments: [attachment("shot.png"), attachment("trace.json")],
      chips: [{ type: "command", id: "review", label: "review" }],
    },
  },
  { label: "Running", args: { isLoading: true, text: SAMPLE_TEXT } },
  { label: "Disabled", args: { disabled: true, text: SAMPLE_TEXT } },
  {
    label: "No selectors",
    args: { showSelectors: false, text: SAMPLE_TEXT },
  },
  {
    label: "Attach only",
    args: {
      showSelectors: false,
      showMode: false,
      showHistory: false,
      showSteerQueue: false,
      contextUsage: null,
    },
  },
  {
    label: "Toolbar hidden",
    args: {
      hideDefaultToolbar: true,
      showHistory: false,
      showSteerQueue: false,
      contextUsage: null,
      text: SAMPLE_TEXT,
    },
  },
  { label: "Context nearly full", args: { contextUsage: nearFullUsage } },
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
  render: (args) => (
    <div className="flex flex-col gap-6">
      {MATRIX.map((variant, index) => (
        <div key={variant.label} className="flex flex-col gap-1">
          <span className="font-medium text-[12px] text-muted-foreground">
            {variant.label}
          </span>
          <div className="max-w-[800px]">
            <PromptInputHarness
              {...args}
              {...variant.args}
              autoFocus={false}
              sessionId={`sb-matrix-${index}`}
            />
          </div>
        </div>
      ))}
    </div>
  ),
};

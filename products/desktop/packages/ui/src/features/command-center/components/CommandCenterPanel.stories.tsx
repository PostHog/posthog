import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { TaskRepositoryChip } from "@posthog/ui/features/canvas/components/TaskRepositoryDialog";
import { PromptHistoryDialog } from "@posthog/ui/features/message-editor/components/PromptHistoryDialog";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import { ReasoningLevelSelector } from "@posthog/ui/features/sessions/components/ReasoningLevelSelector";
import { WorkspaceModeSelect } from "@posthog/ui/features/task-detail/components/WorkspaceModeSelect";
import { DotPatternBackground } from "@posthog/ui/primitives/DotPatternBackground";
import type { Meta, StoryObj } from "@storybook/react-vite";

const modelOption = {
  id: "model",
  name: "Model",
  type: "select" as const,
  currentValue: "gpt-5.6-sol",
  options: [{ value: "gpt-5.6-sol", name: "GPT-5.6 Sol" }],
} satisfies SessionConfigOption;

const thoughtOption = {
  id: "thought",
  name: "Reasoning",
  type: "select" as const,
  currentValue: "high",
  options: [{ value: "high", name: "High" }],
} satisfies SessionConfigOption;

const modeOption = {
  id: "mode",
  name: "Mode",
  type: "select" as const,
  currentValue: "auto",
  options: [{ value: "auto", name: "Auto" }],
} satisfies SessionConfigOption;

function StartingCloudTaskComposer() {
  return (
    <div className="relative h-full px-4">
      <DotPatternBackground className="h-[100.333%]" />
      <div className="-translate-1/2 absolute top-1/2 left-1/2 z-1 flex w-[calc(100%-2rem)] max-w-[600px] flex-col gap-2">
        <div className="absolute bottom-full left-0 mb-2 flex min-w-0 items-center gap-1">
          <WorkspaceModeSelect
            value="cloud"
            onChange={() => {}}
            overrideModes={["cloud"]}
          />
          <TaskRepositoryChip
            cloud
            repositoryCount={0}
            hasFolder={false}
            disabled={false}
            onOpen={() => {}}
          />
        </div>
        <PromptInput
          sessionId="storybook-cloud-task"
          placeholder="What do you want to ship?"
          editorHeight="large"
          autoFocus={false}
          clearOnSubmit={false}
          enableCommands
          enableBashMode={false}
          modeOption={modeOption}
          onModeChange={() => {}}
          historyButton={
            <PromptHistoryDialog
              onSelect={() => {}}
              hasPendingDraft={() => false}
            />
          }
          reasoningSelector={
            <ReasoningLevelSelector
              thoughtOption={thoughtOption}
              modelOption={modelOption}
              adapter="codex"
              onChange={() => {}}
              workspaceMode="cloud"
            />
          }
          onSubmit={() => {}}
        />
      </div>
    </div>
  );
}

const meta: Meta<typeof StartingCloudTaskComposer> = {
  title: "Command Center/New Task Composer",
  component: StartingCloudTaskComposer,
  parameters: {
    layout: "fullscreen",
  },
  decorators: [
    (Story) => (
      <div className="h-[420px] w-[760px] overflow-hidden border border-gray-6 bg-gray-1">
        <Story />
      </div>
    ),
  ],
};

export default meta;
type Story = StoryObj<typeof StartingCloudTaskComposer>;

export const StartingCloudTask: Story = {};

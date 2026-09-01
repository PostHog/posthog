import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import type { AgentAdapter } from "@posthog/ui/features/settings/settingsStore";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { type ReactElement, useState } from "react";
import { within } from "storybook/test";
import { ReasoningLevelSelector } from "./ReasoningLevelSelector";

const harnessOption = (
  harness: AgentAdapter,
  value: string,
  name: string,
): { value: string; name: string; _meta: Record<string, unknown> } => ({
  value,
  name,
  _meta: { "posthog.code/modelHarness": harness },
});

const ANTHROPIC_MODELS = [
  harnessOption("claude", "claude-fable-5", "Claude Fable 5"),
  harnessOption("claude", "claude-opus-5", "Claude Opus 5"),
  harnessOption("claude", "claude-opus-4-8", "Claude Opus 4.8"),
  harnessOption("claude", "claude-opus-4-7", "Claude Opus 4.7"),
  harnessOption("claude", "claude-sonnet-5", "Claude Sonnet 5"),
  harnessOption("claude", "claude-sonnet-4-6", "Claude Sonnet 4.6"),
];

const OPENAI_MODELS = [
  harnessOption("codex", "gpt-5.6-sol", "GPT-5.6 Sol"),
  harnessOption("codex", "gpt-5.6-terra", "GPT-5.6 Terra"),
  harnessOption("codex", "gpt-5.5", "GPT-5.5"),
];

const ZAI_MODELS = [
  harnessOption("claude", "zai-org/glm-5.3-flash", "GLM-5.3 Flash"),
  harnessOption("claude", "zai-org/glm-5.3", "GLM-5.3"),
  harnessOption("claude", "@cf/zai-org/glm-5.2", "GLM-5.2"),
];

const MOONSHOT_MODELS = [
  harnessOption("claude", "moonshotai/kimi-k3", "Kimi K3"),
];

const DEEPSEEK_MODELS = [
  harnessOption(
    "claude",
    "deepseek-ai/deepseek-v4-flash-0731",
    "DeepSeek V4 Flash",
  ),
];

function groupedModelOption(currentValue: string): SessionConfigOption {
  return {
    type: "select",
    id: "model",
    name: "Model",
    category: "model",
    currentValue,
    options: [
      { group: "anthropic", name: "Anthropic", options: ANTHROPIC_MODELS },
      { group: "openai", name: "OpenAI", options: OPENAI_MODELS },
      { group: "zai-org", name: "Z.ai", options: ZAI_MODELS },
      { group: "moonshotai", name: "Moonshot AI", options: MOONSHOT_MODELS },
      { group: "deepseek-ai", name: "DeepSeek", options: DEEPSEEK_MODELS },
    ],
  } as unknown as SessionConfigOption;
}

function effortOption(currentValue: string): SessionConfigOption {
  return {
    type: "select",
    id: "effort",
    name: "Effort",
    category: "thought_level",
    currentValue,
    options: [
      { name: "Low", value: "low" },
      { name: "Medium", value: "medium" },
      {
        name: "High",
        value: "high",
        _meta: { "posthog.code/defaultOption": true },
      },
      { name: "Extra High", value: "xhigh" },
      { name: "Max", value: "max" },
    ],
  } as unknown as SessionConfigOption;
}

function contextWindowOption(): SessionConfigOption {
  return {
    type: "select",
    id: "context_window",
    name: "Context Window",
    category: "_context_window",
    currentValue: "1m",
    options: [
      { name: "200k", value: "200k" },
      {
        name: "1M",
        value: "1m",
        _meta: { "posthog.code/defaultOption": true },
      },
    ],
  } as unknown as SessionConfigOption;
}

function Harness(): ReactElement {
  const [adapter, setAdapter] = useState<AgentAdapter>("claude");
  const [model, setModel] = useState("claude-opus-5");
  const [effort, setEffort] = useState("medium");

  return (
    <div className="flex h-[520px] items-end p-2">
      <ReasoningLevelSelector
        thoughtOption={effortOption(effort)}
        modelOption={groupedModelOption(model)}
        adapter={adapter}
        contextWindowOption={contextWindowOption()}
        onChange={setEffort}
        onModelChange={setModel}
        onAdapterChange={setAdapter}
        onHarnessModelChange={(harness, nextModel) => {
          setAdapter(harness);
          setModel(nextModel);
        }}
        onConfigOptionChange={() => {}}
      />
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Sessions/ReasoningLevelSelector",
  component: Harness,
};

export default meta;
type Story = StoryObj<typeof Harness>;

export const Default: Story = {};

export const GroupedModelSubmenu: Story = {
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("button", { name: /Model and reasoning/ }),
    );
    await userEvent.click(
      await body.findByRole("button", { name: "Advanced" }),
    );
    await userEvent.hover(await body.findByText("Model"));
    await body.findByText("GPT-5.6 Sol");
  },
};

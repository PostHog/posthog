import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { type ReactElement, useState } from "react";
import { within } from "storybook/test";
import { PiModelSelector } from "./PiSessionControls";

const option = (
  harness: "claude" | "codex",
  value: string,
  name: string,
): { value: string; name: string; _meta: Record<string, unknown> } => ({
  value,
  name,
  _meta: { "posthog.code/modelHarness": harness },
});

function groupedModelOption(currentValue: string): SessionConfigOption {
  return {
    type: "select",
    id: "model",
    name: "Model",
    category: "model",
    currentValue,
    options: [
      {
        group: "anthropic",
        name: "Anthropic",
        options: [
          option("claude", "claude-fable-5-1", "Claude Fable 5.1"),
          option("claude", "claude-opus-5", "Claude Opus 5"),
          option("claude", "claude-sonnet-5", "Claude Sonnet 5"),
        ],
      },
      {
        group: "openai",
        name: "OpenAI",
        options: [
          option("codex", "gpt-5.6-sol", "GPT-5.6 Sol"),
          option("codex", "gpt-5.6-terra", "GPT-5.6 Terra"),
          option("codex", "gpt-5.5", "GPT-5.5"),
        ],
      },
      {
        group: "zai-org",
        name: "Z.ai",
        options: [option("claude", "zai-org/glm-5.3", "GLM-5.3")],
      },
    ],
  } as unknown as SessionConfigOption;
}

const piModels = [
  { provider: "posthog" as const, id: "claude-opus-5", name: "Claude Opus 5" },
  { provider: "posthog" as const, id: "gpt-5.6-terra", name: "GPT-5.6 Terra" },
  { provider: "posthog" as const, id: "zai-org/glm-5.3", name: "GLM-5.3" },
];

function Harness(): ReactElement {
  const [modelId, setModelId] = useState("gpt-5.6-terra");
  const currentModel = piModels.find((model) => model.id === modelId);

  return (
    <div className="flex h-[480px] items-end p-2">
      <PiModelSelector
        models={piModels}
        currentModel={currentModel}
        thinkingLevel="high"
        thinkingLevels={["off", "low", "medium", "high"]}
        onChange={(model) => setModelId(model.id)}
        onThinkingLevelChange={() => {}}
        onHarnessChange={() => {}}
        modelOption={groupedModelOption(modelId)}
        onGatewayModelSelect={setModelId}
      />
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Pi Sessions/PiModelSelector",
  component: Harness,
};

export default meta;
type Story = StoryObj<typeof Harness>;

export const Default: Story = {};

export const FullCatalogSubmenu: Story = {
  play: async ({ canvas, canvasElement, userEvent }): Promise<void> => {
    const body = within(canvasElement.ownerDocument.body);
    await userEvent.click(
      canvas.getByRole("button", { name: /Model and reasoning/ }),
    );
    await userEvent.hover(await body.findByText("Model"));
    await body.findByText("GPT-5.6 Sol");
  },
};

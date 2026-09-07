import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuTrigger,
} from "@posthog/quill";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { ModelCostFooter } from "./ModelCostChip";
import { ModelRadioItem } from "./ModelRadioItem";

const MODELS = [
  { value: "claude-haiku-4-5", name: "Claude Haiku 4.5" },
  { value: "claude-sonnet-5", name: "Claude Sonnet 5" },
  { value: "claude-opus-5", name: "Claude Opus 5" },
  { value: "claude-fable-5", name: "Claude Fable 5" },
  { value: "gpt-5.6-sol", name: "GPT-5.6 Sol" },
  { value: "gpt-5.6-terra", name: "GPT-5.6 Terra" },
  { value: "gpt-5.6-luna", name: "GPT-5.6 Luna" },
  { value: "glm-5.3", name: "GLM 5.3" },
  { value: "some-custom-model", name: "Custom model" },
];

/** The model list with cost chips, held open for visual review. */
function OpenModelList() {
  return (
    <div className="flex h-[420px] items-end p-6">
      <DropdownMenu open>
        <DropdownMenuTrigger
          render={<Button size="sm">Claude Sonnet 5</Button>}
        />
        <DropdownMenuContent align="start" side="top" className="min-w-[230px]">
          <DropdownMenuRadioGroup value="claude-sonnet-5">
            {MODELS.map((model) => (
              <ModelRadioItem key={model.value} model={model} />
            ))}
          </DropdownMenuRadioGroup>
          <ModelCostFooter />
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

const meta: Meta<typeof OpenModelList> = {
  title: "Sessions/ModelCostChip",
  component: OpenModelList,
};

export default meta;
type Story = StoryObj<typeof OpenModelList>;

export const OpenList: Story = {};

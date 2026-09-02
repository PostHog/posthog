import {
  type Adapter,
  type CloudTaskConfigOption,
  DEFAULT_GATEWAY_MODEL,
  restrictedModelMeta,
  type SupportedReasoningEffort,
} from "@posthog/shared";
import { expect, it } from "vitest";
import {
  resolveCloudComposerAdapterChange,
  resolveCloudComposerModelChange,
} from "./composerModelPolicy";

it.each([
  [
    "claude",
    { adapter: "codex", mode: "auto", model: "gpt-5.5", reasoning: "high" },
  ],
  [
    "codex",
    {
      adapter: "claude",
      mode: "plan",
      model: DEFAULT_GATEWAY_MODEL,
      reasoning: "high",
    },
  ],
] as const)(
  "resets composer defaults when switching from %s",
  (adapter, expected) => {
    expect(resolveCloudComposerAdapterChange(adapter)).toEqual(expected);
  },
);

const modelOption: CloudTaskConfigOption = {
  id: "model",
  name: "Model",
  type: "select",
  currentValue: DEFAULT_GATEWAY_MODEL,
  options: [
    { value: DEFAULT_GATEWAY_MODEL, name: "Claude" },
    { value: "restricted", name: "Restricted", _meta: restrictedModelMeta() },
    { value: "gpt-5.3-codex", name: "Codex" },
  ],
  category: "model",
  description: "Choose a model",
};

it.each([
  ["claude", DEFAULT_GATEWAY_MODEL, "high", DEFAULT_GATEWAY_MODEL, "high"],
  ["claude", "restricted", "high", DEFAULT_GATEWAY_MODEL, "high"],
  ["claude", "missing", "high", DEFAULT_GATEWAY_MODEL, "high"],
  ["codex", "gpt-5.3-codex", "xhigh", "gpt-5.3-codex", "high"],
] as const)(
  "resolves %s model %s with %s reasoning",
  (adapter, requestedModel, reasoning, expectedModel, expectedReasoning) => {
    expect(
      resolveCloudComposerModelChange({
        adapter: adapter as Adapter,
        modelOption,
        requestedModel,
        reasoning: reasoning as SupportedReasoningEffort,
      }),
    ).toEqual({ model: expectedModel, reasoning: expectedReasoning });
  },
);

import type { Adapter } from "@posthog/shared";
import {
  adapterForModelId,
  DEFAULT_GATEWAY_MODEL,
  getReasoningEffortOptions,
  type SupportedReasoningEffort,
  supportsFastMode,
} from "@posthog/shared";
import { create } from "zustand";

interface ComposerConfig {
  // The harness follows the model: GPT models run on Codex, the rest on Claude Code.
  adapter: Adapter;
  model: string;
  reasoning: SupportedReasoningEffort;
}

interface ComposerState extends ComposerConfig {
  setModel: (model: string) => void;
  setReasoning: (reasoning: SupportedReasoningEffort) => void;
  reset: () => void;
}

const defaults: ComposerConfig = {
  adapter: "claude",
  model: DEFAULT_GATEWAY_MODEL,
  reasoning: "high",
};

// Keep the effort valid for the model, preferring the current one.
function clampReasoning(
  adapter: Adapter,
  model: string,
  reasoning: SupportedReasoningEffort,
): SupportedReasoningEffort {
  const options = getReasoningEffortOptions(adapter, model);
  if (!options || options.some((option) => option.value === reasoning)) {
    return reasoning;
  }
  return options[options.length - 1]?.value ?? reasoning;
}

export const useComposer = create<ComposerState>((set, get) => ({
  ...defaults,
  setModel: (model) => {
    const adapter = adapterForModelId(model);
    set({
      model,
      adapter,
      reasoning: clampReasoning(adapter, model, get().reasoning),
    });
  },
  setReasoning: (reasoning) => set({ reasoning }),
  reset: () => set({ ...defaults }),
}));

// The run request fields for the current picks, in api-client's names.
export function currentRunConfig() {
  const { adapter, model, reasoning } = useComposer.getState();
  return {
    adapter,
    model,
    reasoningLevel:
      getReasoningEffortOptions(adapter, model) === null
        ? undefined
        : reasoning,
    ...(supportsFastMode(model) ? { fastMode: false } : {}),
  };
}

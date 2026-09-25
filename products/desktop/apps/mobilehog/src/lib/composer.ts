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
  contextId: string;
  saved: Record<string, ComposerConfig>;
  selectContext: (
    id: string,
    model?: string,
    reasoning?: SupportedReasoningEffort,
  ) => void;
  setModel: (model: string) => void;
  setReasoning: (reasoning: SupportedReasoningEffort) => void;
  reset: () => void;
  clear: () => void;
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
  contextId: "new",
  saved: {},
  selectContext: (id, model, reasoning) => {
    const current = get();
    if (current.contextId === id) return;
    const saved = {
      ...current.saved,
      [current.contextId]: {
        model: current.model,
        adapter: current.adapter,
        reasoning: current.reasoning,
      },
    };
    const adapter = model ? adapterForModelId(model) : defaults.adapter;
    set({
      contextId: id,
      saved,
      ...(saved[id] ?? {
        adapter,
        model: model ?? defaults.model,
        reasoning: clampReasoning(
          adapter,
          model ?? defaults.model,
          reasoning ?? defaults.reasoning,
        ),
      }),
    });
  },
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
  clear: () => set({ ...defaults, contextId: "new", saved: {} }),
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

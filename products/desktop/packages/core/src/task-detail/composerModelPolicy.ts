import {
  type Adapter,
  type CloudTaskConfigOption,
  DEFAULT_CODEX_MODEL,
  DEFAULT_GATEWAY_MODEL,
  DEFAULT_REASONING_EFFORT,
  type ExecutionMode,
  isRestrictedModelOption,
  isSupportedReasoningEffort,
  type SupportedReasoningEffort,
} from "@posthog/shared";
import { getDefaultExecutionModeForAdapter } from "../sessions/executionModes";

export interface CloudComposerSelection {
  adapter: Adapter;
  mode: ExecutionMode;
  model: string;
  reasoning: SupportedReasoningEffort;
}

export function resolveCloudComposerAdapterChange(
  currentAdapter: Adapter,
): CloudComposerSelection {
  const adapter: Adapter = currentAdapter === "claude" ? "codex" : "claude";
  return {
    adapter,
    mode: getDefaultExecutionModeForAdapter(adapter),
    model: adapter === "codex" ? DEFAULT_CODEX_MODEL : DEFAULT_GATEWAY_MODEL,
    reasoning: DEFAULT_REASONING_EFFORT,
  };
}

export function resolveCloudComposerModelChange({
  adapter,
  modelOption,
  requestedModel,
  reasoning,
}: {
  adapter: Adapter;
  modelOption: CloudTaskConfigOption;
  requestedModel: string;
  reasoning: SupportedReasoningEffort;
}): { model: string; reasoning: SupportedReasoningEffort } {
  const selected = modelOption.options.find(
    (option) => option.value === requestedModel,
  );
  const model =
    selected && !isRestrictedModelOption(selected._meta)
      ? requestedModel
      : modelOption.currentValue;

  return {
    model,
    reasoning: isSupportedReasoningEffort(adapter, model, reasoning)
      ? reasoning
      : DEFAULT_REASONING_EFFORT,
  };
}

import type { LoopSchemas } from "@posthog/api-client/loops";
import { GLM_MODEL_FLAG } from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { Flex } from "@radix-ui/themes";
import { useMemo } from "react";
import { useLoopModelConfigOptions } from "../hooks/useLoopModelConfigOptions";
import {
  clampLoopReasoningEffort,
  loopModelOptions,
  loopReasoningEffortOptions,
} from "../loopModels";
import { Field } from "./LoopFormPrimitives";

const ADAPTER_OPTIONS: {
  value: LoopSchemas.LoopRuntimeAdapterEnum;
  label: string;
}[] = [
  { value: "claude", label: "Claude Code" },
  { value: "codex", label: "Codex" },
];

const AUTO_REASONING_VALUE = "auto";
const DEFAULT_MODEL_VALUE = "__default__";

interface LoopModelFieldsProps {
  adapter: LoopSchemas.LoopRuntimeAdapterEnum;
  model: string;
  reasoningEffort: LoopSchemas.LoopReasoningEffortEnum | null;
  onAdapterChange: (adapter: LoopSchemas.LoopRuntimeAdapterEnum) => void;
  onModelChange: (model: string) => void;
  onReasoningEffortChange: (
    effort: LoopSchemas.LoopReasoningEffortEnum | null,
  ) => void;
  disabled?: boolean;
}

/**
 * Static model configuration for a loop: model, adapter, and reasoning effort.
 * Loops have no live agent session, so the interactive
 * `UnifiedModelSelector`/`ReasoningLevelSelector` (which read a session's
 * `SessionConfigOption`) don't apply here; instead this presents the same
 * per-adapter choices as the main create-task picker (see `loopModels.ts`),
 * so every selectable combo passes the server's validation in
 * `process_task/utils.py`. Adapter and model switches clamp a now-unsupported
 * reasoning effort back to Auto for the same reason.
 */
export function LoopModelFields({
  adapter,
  model,
  reasoningEffort,
  onAdapterChange,
  onModelChange,
  onReasoningEffortChange,
  disabled,
}: LoopModelFieldsProps) {
  const glmEnabled = useFeatureFlag(GLM_MODEL_FLAG);
  const configOptions = useLoopModelConfigOptions(adapter);

  const modelOptions = useMemo(
    () => [
      { value: DEFAULT_MODEL_VALUE, label: "Default (recommended)" },
      ...loopModelOptions(adapter, configOptions, {
        glmEnabled,
        pinnedModel: model,
      }),
    ],
    [adapter, configOptions, glmEnabled, model],
  );

  const reasoningOptions = useMemo(
    () => [
      { value: AUTO_REASONING_VALUE, label: "Auto" },
      ...loopReasoningEffortOptions(adapter, model),
    ],
    [adapter, model],
  );

  const handleAdapterChange = (value: string) => {
    const nextAdapter = value as LoopSchemas.LoopRuntimeAdapterEnum;
    onAdapterChange(nextAdapter);
    // Adapters have disjoint model catalogs, so a pinned model can't carry over.
    if (model) onModelChange("");
    const clamped = clampLoopReasoningEffort(nextAdapter, "", reasoningEffort);
    if (clamped !== reasoningEffort) onReasoningEffortChange(clamped);
  };

  const handleModelChange = (value: string) => {
    const nextModel = value === DEFAULT_MODEL_VALUE ? "" : value;
    onModelChange(nextModel);
    const clamped = clampLoopReasoningEffort(
      adapter,
      nextModel,
      reasoningEffort,
    );
    if (clamped !== reasoningEffort) onReasoningEffortChange(clamped);
  };

  return (
    <Flex direction="column" gap="4">
      <Field
        label="Model"
        hint="Default lets PostHog pick the model each run; choose one to pin it."
      >
        <SettingsOptionSelect
          value={model || DEFAULT_MODEL_VALUE}
          options={modelOptions}
          placeholder="Default (recommended)"
          onValueChange={handleModelChange}
          disabled={disabled}
          size="lg"
          ariaLabel="Model"
        />
      </Field>

      <Flex gap="4" wrap="wrap">
        <Field label="Adapter" className="min-w-[180px] flex-1">
          <SettingsOptionSelect
            value={adapter}
            options={ADAPTER_OPTIONS}
            onValueChange={handleAdapterChange}
            disabled={disabled}
            size="lg"
            ariaLabel="Adapter"
          />
        </Field>

        <Field label="Reasoning effort" className="min-w-[180px] flex-1">
          <SettingsOptionSelect
            value={reasoningEffort ?? AUTO_REASONING_VALUE}
            options={reasoningOptions}
            placeholder="Auto"
            onValueChange={(value) =>
              onReasoningEffortChange(
                value === AUTO_REASONING_VALUE
                  ? null
                  : (value as LoopSchemas.LoopReasoningEffortEnum),
              )
            }
            disabled={disabled}
            size="lg"
            ariaLabel="Reasoning effort"
          />
        </Field>
      </Flex>
    </Flex>
  );
}

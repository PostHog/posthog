import type { LoopSchemas } from "@posthog/api-client/loops";
import { useModelRolloutFlags } from "@posthog/ui/features/sessions/useModelRolloutFlags";
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
  /** Hidden for a workflow-backed loop: the task step picks the adapter itself. */
  adapterEditable?: boolean;
}

/**
 * Static model configuration for a loop: model, adapter, and reasoning effort.
 * Loops have no live agent session, so the interactive
 * `ReasoningLevelSelector` (which reads a session's `SessionConfigOption`)
 * doesn't apply here; instead this presents the same
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
  adapterEditable = true,
}: LoopModelFieldsProps) {
  const modelFlags = useModelRolloutFlags();
  const configOptions = useLoopModelConfigOptions(adapter);

  const modelOptions = useMemo(
    () => [
      { value: DEFAULT_MODEL_VALUE, label: "Default (recommended)" },
      ...loopModelOptions(adapter, configOptions, {
        glmEnabled: modelFlags.glm,
        glm53Enabled: modelFlags.glm53,
        glm53FlashEnabled: modelFlags.glm53Flash,
        kimiEnabled: modelFlags.kimi,
        deepseekEnabled: modelFlags.deepseek,
        pinnedModel: model,
      }),
    ],
    [adapter, configOptions, modelFlags, model],
  );

  // A workflow only stores the effort next to a pinned model, so offering
  // efforts for the default model would confirm a value that is never saved.
  const effortNeedsModel = !adapterEditable && !model;

  const reasoningOptions = useMemo(
    () => [
      { value: AUTO_REASONING_VALUE, label: "Auto" },
      ...(effortNeedsModel ? [] : loopReasoningEffortOptions(adapter, model)),
    ],
    [adapter, model, effortNeedsModel],
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
    const clamped =
      !adapterEditable && !nextModel
        ? null
        : clampLoopReasoningEffort(adapter, nextModel, reasoningEffort);
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
        {adapterEditable ? (
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
        ) : null}

        <Field
          label="Reasoning effort"
          className="min-w-[180px] flex-1"
          hint={
            effortNeedsModel
              ? "Pick a model to set reasoning effort."
              : undefined
          }
        >
          <SettingsOptionSelect
            value={reasoningEffort ?? AUTO_REASONING_VALUE}
            options={reasoningOptions}
            onValueChange={(value) =>
              onReasoningEffortChange(
                value === AUTO_REASONING_VALUE
                  ? null
                  : (value as LoopSchemas.LoopReasoningEffortEnum),
              )
            }
            disabled={disabled || effortNeedsModel}
            size="lg"
            ariaLabel="Reasoning effort"
          />
        </Field>
      </Flex>
    </Flex>
  );
}

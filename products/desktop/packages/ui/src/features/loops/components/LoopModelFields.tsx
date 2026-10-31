import type { LoopSchemas } from "@posthog/ui/features/loops/loopSchemas";
import { useModelRolloutFlags } from "@posthog/ui/features/sessions/useModelRolloutFlags";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { useMemo } from "react";
import { useLoopModelConfigOptions } from "../hooks/useLoopModelConfigOptions";
import {
  clampLoopReasoningEffort,
  loopModelOptions,
  loopReasoningEffortOptions,
} from "../loopModels";
import { Field } from "./LoopFormPrimitives";

const AUTO_REASONING_VALUE = "auto";
const DEFAULT_MODEL_VALUE = "__default__";

interface LoopModelFieldsProps {
  adapter: LoopSchemas.LoopRuntimeAdapterEnum;
  model: string;
  reasoningEffort: LoopSchemas.LoopReasoningEffortEnum | null;
  onModelChange: (model: string) => void;
  onReasoningEffortChange: (
    effort: LoopSchemas.LoopReasoningEffortEnum | null,
  ) => void;
  disabled?: boolean;
}

/**
 * Static model configuration for a loop: model and reasoning effort.
 * Loops have no live agent session, so the interactive
 * `ReasoningLevelSelector` (which reads a session's `SessionConfigOption`)
 * doesn't apply here; instead this presents the same
 * per-adapter choices as the main create-task picker (see `loopModels.ts`),
 * so every selectable combo passes the server's validation in
 * `process_task/utils.py`. A model switch clamps a now-unsupported reasoning
 * effort back to Auto for the same reason.
 */
export function LoopModelFields({
  adapter,
  model,
  reasoningEffort,
  onModelChange,
  onReasoningEffortChange,
  disabled,
}: LoopModelFieldsProps) {
  const modelFlags = useModelRolloutFlags();
  const configOptions = useLoopModelConfigOptions(adapter);

  const modelOptions = useMemo(
    () => [
      { value: DEFAULT_MODEL_VALUE, label: "Default (recommended)" },
      ...loopModelOptions(adapter, configOptions, {
        flags: modelFlags,
        pinnedModel: model,
      }),
    ],
    [adapter, configOptions, modelFlags, model],
  );

  // A workflow only stores the effort next to a pinned model, so offering
  // efforts for the default model would confirm a value that is never saved.
  const effortNeedsModel = !model;

  const reasoningOptions = useMemo(
    () => [
      { value: AUTO_REASONING_VALUE, label: "Auto" },
      ...(effortNeedsModel ? [] : loopReasoningEffortOptions(adapter, model)),
    ],
    [adapter, model, effortNeedsModel],
  );

  const handleModelChange = (value: string) => {
    const nextModel = value === DEFAULT_MODEL_VALUE ? "" : value;
    onModelChange(nextModel);
    const clamped = nextModel
      ? clampLoopReasoningEffort(adapter, nextModel, reasoningEffort)
      : null;
    if (clamped !== reasoningEffort) onReasoningEffortChange(clamped);
  };

  return (
    <div className="flex flex-col gap-4">
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

      <div className="flex flex-wrap gap-4">
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
      </div>
    </div>
  );
}

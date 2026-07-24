import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { getReasoningEffortOptions } from "@posthog/agent/adapters/reasoning-effort";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { flattenSelectOptions, isRestrictedModelOption } from "@posthog/shared";

export interface LoopModelOption {
  value: string;
  label: string;
}

// Mirrors DEFAULT_MODEL_BY_RUNTIME_ADAPTER in posthog's
// products/tasks/backend/temporal/process_task/utils.py: the model a loop
// fires with when none is pinned, and the one the serializer validates a
// blank-model loop's reasoning effort against.
export const LOOP_DEFAULT_MODELS: Record<
  LoopSchemas.LoopRuntimeAdapterEnum,
  { id: string; label: string }
> = {
  claude: { id: "claude-sonnet-5", label: "Claude Sonnet 5" },
  codex: { id: "gpt-5", label: "GPT-5" },
};

function isGlmModelId(modelId: string): boolean {
  return modelId.toLowerCase().includes("glm");
}

// Served-catalog stand-in while the preview config loads or when the request
// fails, so the picker never collapses to "Default" alone. Matches the
// backend's per-adapter catalogs in process_task/utils.py minus client-blocked
// models; the served catalog stays authoritative once it arrives.
const FALLBACK_MODEL_OPTIONS: Record<
  LoopSchemas.LoopRuntimeAdapterEnum,
  LoopModelOption[]
> = {
  claude: [
    { value: "claude-sonnet-4-6", label: "Claude Sonnet 4.6" },
    { value: "claude-opus-4-7", label: "Claude Opus 4.7" },
    { value: "claude-opus-4-8", label: "Claude Opus 4.8" },
    { value: "claude-sonnet-5", label: "Claude Sonnet 5" },
    { value: "claude-fable-5", label: "Claude Fable 5" },
    { value: "@cf/zai-org/glm-5.2", label: "GLM-5.2" },
  ],
  codex: [
    { value: "gpt-5", label: "GPT-5" },
    { value: "gpt-5.5", label: "GPT-5.5" },
    { value: "gpt-5.6-sol", label: "GPT-5.6 Sol" },
    { value: "gpt-5.6-terra", label: "GPT-5.6 Terra" },
    { value: "gpt-5.6-luna", label: "GPT-5.6 Luna" },
  ],
};

/** The model a loop's runs use, for display: the pinned id, or the adapter's
 * loop default (which differs from the live-session default the
 * ReportModelResolver serves, so it can't be resolved from there). */
export function formatLoopModel(
  adapter: LoopSchemas.LoopRuntimeAdapterEnum,
  configuredModel: string,
): string {
  return configuredModel || `${LOOP_DEFAULT_MODELS[adapter].label} (default)`;
}

/**
 * Pinnable models for a loop, derived from the same per-adapter preview
 * config that feeds the main create-task picker, so the loops picker offers
 * exactly the ids the loops API accepts. Restricted (plan-locked) models are
 * dropped, GLM is flag-gated like the main picker, and the currently pinned
 * model always stays selectable so an existing loop's model never drops out.
 */
export function loopModelOptions(
  adapter: LoopSchemas.LoopRuntimeAdapterEnum,
  configOptions: SessionConfigOption[],
  { glmEnabled, pinnedModel }: { glmEnabled: boolean; pinnedModel: string },
): LoopModelOption[] {
  const modelOption = configOptions.find(
    (option) => option.category === "model" || option.id === "model",
  );
  const served =
    modelOption?.type === "select"
      ? flattenSelectOptions(modelOption.options)
          .filter((option) => !isRestrictedModelOption(option._meta))
          .map((option) => ({
            value: option.value,
            label: option.name ?? option.value,
          }))
      : [];
  const options = (
    served.length > 0 ? served : FALLBACK_MODEL_OPTIONS[adapter]
  ).filter(
    (option) =>
      glmEnabled || option.value === pinnedModel || !isGlmModelId(option.value),
  );
  if (pinnedModel && !options.some((option) => option.value === pinnedModel)) {
    options.push({ value: pinnedModel, label: pinnedModel });
  }
  return options;
}

/** Efforts the loops API accepts for the model that would actually run:
 * the pinned model, or the adapter's default when the loop leaves it unset. */
export function loopReasoningEffortOptions(
  adapter: LoopSchemas.LoopRuntimeAdapterEnum,
  model: string,
): { value: LoopSchemas.LoopReasoningEffortEnum; label: string }[] {
  const effectiveModel = model || LOOP_DEFAULT_MODELS[adapter].id;
  const options = getReasoningEffortOptions(adapter, effectiveModel) ?? [];
  return options.map((option) => ({ value: option.value, label: option.name }));
}

/** The effort unchanged when the effective model supports it, else null
 * (auto), so an adapter or model switch never leaves an invalid combo. */
export function clampLoopReasoningEffort(
  adapter: LoopSchemas.LoopRuntimeAdapterEnum,
  model: string,
  effort: LoopSchemas.LoopReasoningEffortEnum | null,
): LoopSchemas.LoopReasoningEffortEnum | null {
  if (effort === null) return null;
  return loopReasoningEffortOptions(adapter, model).some(
    (option) => option.value === effort,
  )
    ? effort
    : null;
}

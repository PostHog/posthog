import type { SessionConfigOption } from "@agentclientprotocol/sdk";
import { getReasoningEffortOptions } from "@posthog/agent/adapters/reasoning-effort";
import type { LoopSchemas } from "@posthog/api-client/loops";
import {
  flattenSelectOptions,
  isDeepseekModelId,
  isDefaultSelectOption,
  isGlm53FlashModelId,
  isGlm53ModelId,
  isGlmModelId,
  isRestrictedModelOption,
  selectOptionDocsUrl,
} from "@posthog/shared";
import {
  DEFAULT_MODEL_BY_RUNTIME_ADAPTER,
  labelForModel,
} from "@posthog/shared/model-catalog";

export interface LoopModelOption {
  value: string;
  label: string;
}

// The name the catalog resolved for a model when it was generated. Every surface reads
// it from there, so a model is named the same offline as it is in the served list. An id
// the catalog does not carry shows as itself.
function catalogLabel(id: string): string {
  return labelForModel(id) ?? id;
}

// The model a loop fires with when none is pinned, and the one the serializer
// validates a blank-model loop's reasoning effort against. Both the id and its
// name come from the shared catalog, so neither can disagree with what the
// backend applies.
export const LOOP_DEFAULT_MODELS: Record<
  LoopSchemas.LoopRuntimeAdapterEnum,
  { id: string; label: string }
> = {
  claude: {
    id: DEFAULT_MODEL_BY_RUNTIME_ADAPTER.claude,
    label: catalogLabel(DEFAULT_MODEL_BY_RUNTIME_ADAPTER.claude),
  },
  codex: {
    id: DEFAULT_MODEL_BY_RUNTIME_ADAPTER.codex,
    label: catalogLabel(DEFAULT_MODEL_BY_RUNTIME_ADAPTER.codex),
  },
};

function isKimiModelId(modelId: string): boolean {
  return modelId === "moonshotai/kimi-k3";
}

// Served-catalog stand-in while the preview config loads or when the request
// fails, so the picker never collapses to "Default" alone. The served catalog is
// authoritative once it arrives.
//
// The ids are a deliberate subset, not the whole catalog: an offline picker offers
// what someone should reach for without a network, which is fewer models than the
// catalog serves. `everyFallbackModelIsServedByTheCatalog` in the tests holds the
// subset to models the loops serializer still accepts.
const FALLBACK_MODEL_IDS: Record<
  LoopSchemas.LoopRuntimeAdapterEnum,
  readonly string[]
> = {
  claude: [
    "claude-opus-4-8",
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-fable-5-1",
    "zai-org/glm-5.3",
    "zai-org/glm-5.3-flash",
    "moonshotai/kimi-k3",
  ],
  codex: ["gpt-5", "gpt-5.5", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"],
};

// Named from the catalog, so a model does not change label when the preview config drops.
const FALLBACK_MODEL_OPTIONS: Record<
  LoopSchemas.LoopRuntimeAdapterEnum,
  LoopModelOption[]
> = {
  claude: fallbackOptionsFor("claude"),
  codex: fallbackOptionsFor("codex"),
};

function fallbackOptionsFor(
  adapter: LoopSchemas.LoopRuntimeAdapterEnum,
): LoopModelOption[] {
  return FALLBACK_MODEL_IDS[adapter].map((id) => ({
    value: id,
    label: catalogLabel(id),
  }));
}

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
 * dropped, staged models carry the same rollout flags as the main picker
 * (`useModelRolloutFlags`), and the currently pinned
 * model always stays selectable so an existing loop's model never drops out.
 */
export function loopModelOptions(
  adapter: LoopSchemas.LoopRuntimeAdapterEnum,
  configOptions: SessionConfigOption[],
  {
    glmEnabled,
    glm53Enabled,
    glm53FlashEnabled,
    kimiEnabled,
    deepseekEnabled,
    pinnedModel,
  }: {
    glmEnabled: boolean;
    glm53Enabled?: boolean;
    glm53FlashEnabled?: boolean;
    kimiEnabled?: boolean;
    deepseekEnabled?: boolean;
    pinnedModel: string;
  },
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
  const options = (served.length > 0 ? served : FALLBACK_MODEL_OPTIONS[adapter])
    .filter(
      (option) =>
        (isGlm53FlashModelId(option.value)
          ? glm53FlashEnabled
          : isGlm53ModelId(option.value)
            ? glm53Enabled
            : glmEnabled) ||
        option.value === pinnedModel ||
        !isGlmModelId(option.value),
    )
    .filter(
      (option) =>
        kimiEnabled ||
        option.value === pinnedModel ||
        !isKimiModelId(option.value),
    )
    .filter(
      (option) =>
        deepseekEnabled ||
        option.value === pinnedModel ||
        !isDeepseekModelId(option.value),
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
): {
  value: LoopSchemas.LoopReasoningEffortEnum;
  label: string;
  isDefault?: boolean;
  docsUrl?: string;
}[] {
  const effectiveModel = model || LOOP_DEFAULT_MODELS[adapter].id;
  const options = getReasoningEffortOptions(adapter, effectiveModel) ?? [];
  return options.map((option) => ({
    value: option.value,
    label: option.name,
    isDefault: isDefaultSelectOption(option._meta),
    docsUrl: selectOptionDocsUrl(option._meta),
  }));
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

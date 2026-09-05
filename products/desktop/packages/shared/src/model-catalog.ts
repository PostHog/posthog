import type { Adapter } from "./adapter";
import {
  FALLBACK_REASONING_EFFORTS,
  FAMILY_REASONING_EFFORTS,
  MODELS,
  PROVIDER_BY_RUNTIME_ADAPTER,
  type ReasoningEffort,
} from "./model-catalog.generated";

export {
  type CatalogModel,
  DEFAULT_MODEL_BY_RUNTIME_ADAPTER,
  MODELS,
  PROVIDER_BY_RUNTIME_ADAPTER,
  REASONING_EFFORTS,
  type ReasoningEffort,
  RUNTIME_ADAPTERS,
  type RuntimeAdapter,
} from "./model-catalog.generated";

/**
 * The form a model id is looked up under. The gateway serves some models both bare and
 * provider-qualified (`openai/gpt-5.6-sol`) and a picker may hand back either, so folding
 * the two together is what stops one model from having two answers. Only the provider
 * prefixes the catalog knows are stripped, leaving ids that carry a slash of their own
 * (`@cf/zai-org/glm-5.2`) intact.
 */
export function normalizeModelId(modelId: string): string {
  const normalized = modelId.trim().toLowerCase();
  for (const provider of Object.values(PROVIDER_BY_RUNTIME_ADAPTER)) {
    if (normalized.startsWith(`${provider}/`)) {
      return normalized.slice(provider.length + 1);
    }
  }
  return normalized;
}

/**
 * The efforts this model may run at, empty when it takes no effort at all.
 *
 * Resolved in three steps: the exact id, then the family it belongs to, then what the
 * adapter accepts generally. Codex passes any `gpt-*` identifier through, so a newly
 * served id still runs, while Claude has no fallback and yields nothing — which is what
 * makes the backend reject it. Mirrors `reasoning_efforts_for` in
 * products/tasks/backend/model_catalog.py, so a selection this offers is one a run can
 * actually use.
 */
export function reasoningEffortsForModel(
  adapter: Adapter,
  modelId: string,
): readonly ReasoningEffort[] {
  const normalized = normalizeModelId(modelId);
  const model = MODELS.find(
    (candidate) =>
      candidate.runtimeAdapter === adapter && candidate.id === normalized,
  );
  if (model) return model.reasoningEfforts;
  // Longest matching prefix wins, so the table's declaration order is free.
  const family = FAMILY_REASONING_EFFORTS.filter(
    (candidate) =>
      candidate.runtimeAdapter === adapter &&
      normalized.startsWith(candidate.prefix),
  ).sort((a, b) => b.prefix.length - a.prefix.length)[0];
  return family?.reasoningEfforts ?? FALLBACK_REASONING_EFFORTS[adapter] ?? [];
}

/**
 * The name the catalog pins for a model, or `undefined` to let the caller format the id.
 *
 * Only the ids whose derived name reads wrong carry one, so a caller keeps its formatter
 * for everything else. Mirrors `label_for_model` in
 * products/tasks/backend/model_catalog.py, so both surfaces name a model identically.
 */
export function labelForModel(modelId: string): string | undefined {
  const normalized = normalizeModelId(modelId);
  return MODELS.find((candidate) => candidate.id === normalized)?.label;
}

import type { Adapter } from "./adapter";
import {
  COST_BASELINE_MODEL,
  MODEL_FAMILY_ACCESS_FLAGS,
  NEVER_OFFERED_MODELS,
  OFFERED_MODEL_FAMILIES,
  OFFERED_VERSIONS_PER_FAMILY,
  PROVIDER_BY_RUNTIME_ADAPTER,
  REASONING_EFFORTS,
  type ReasoningEffort,
} from "./model-catalog.generated";

export {
  COST_BASELINE_MODEL,
  DEFAULT_MODEL_BY_RUNTIME_ADAPTER,
  PROVIDER_BY_RUNTIME_ADAPTER,
  REASONING_EFFORTS,
  type ReasoningEffort,
  RUNTIME_ADAPTERS,
  RUNTIME_OPTIONS,
  type Runtime,
  type RuntimeAdapter,
  type RuntimeOption,
} from "./model-catalog.generated";

export const ANTHROPIC_MESSAGES_SHAPE = "anthropic-messages";
export const OPENAI_RESPONSES_SHAPE = "openai-responses";

const FAST_MODE_MODEL_FAMILIES: readonly string[] = ["claude-opus"];
const LONG_CONTEXT_WINDOW = 1_000_000;
const ALIAS_NAME_SUFFIX = " (latest)";
const COST_RATIO_TOLERANCE = 0.1;

export interface ListedModel {
  id: string;
  owned_by?: string;
  context_window?: number;
  api_shapes?: string[];
  name?: string;
  family?: string;
  release_date?: string;
  /** Absent when the gateway says nothing about the model's reasoning. */
  reasoning_efforts?: string[];
  input_per_mtok?: number;
  output_per_mtok?: number;
  allowed?: boolean;
}

export interface ModelCost {
  inputPerMtok: number;
  outputPerMtok: number;
}

interface GatewayListing {
  models: Map<string, ListedModel>;
  offered: Set<string>;
}

// The agent package inlines its own copy of this module into each of its entries, so the
// listing lives on globalThis where every copy in the process reads the same one.
const LISTING = Symbol.for("posthog.agentContracts.gatewayListing");

function listing(): GatewayListing {
  const holder = globalThis as { [LISTING]?: GatewayListing };
  holder[LISTING] ??= { models: new Map(), offered: new Set() };
  return holder[LISTING];
}

export function normalizeModelId(modelId: string): string {
  const normalized = modelId.trim().toLowerCase();
  for (const provider of Object.values(PROVIDER_BY_RUNTIME_ADAPTER)) {
    if (normalized.startsWith(`${provider}/`)) {
      return normalized.slice(provider.length + 1);
    }
  }
  return normalized;
}

function listingKey(modelId: string): string {
  return normalizeModelId(modelId).replace(/^@cf\//, "");
}

function familyOf(model: ListedModel): string {
  return model.family || listingKey(model.id);
}

function offeredIdsOf(models: readonly ListedModel[]): Set<string> {
  // Django's task model list names no families and holds only the models the product offers.
  if (!models.some((model) => model.family)) {
    return new Set(models.map((model) => listingKey(model.id)));
  }
  const families = new Map<string, Map<string, ListedModel>>();
  for (const model of models) {
    const versions = families.get(familyOf(model)) ?? new Map();
    if (!versions.has(listingKey(model.id))) {
      versions.set(listingKey(model.id), model);
    }
    families.set(familyOf(model), versions);
  }

  const offered = new Set<string>();
  for (const [family, versions] of families) {
    if (!OFFERED_MODEL_FAMILIES.includes(family)) continue;
    const released = (id: string): string =>
      versions.get(id)?.release_date ?? "";
    const ids = [...versions.keys()];
    const current = ids.every(released)
      ? ids
          .sort((a, b) =>
            released(a) === released(b)
              ? 0
              : released(a) < released(b)
                ? 1
                : -1,
          )
          .slice(0, OFFERED_VERSIONS_PER_FAMILY)
      : ids;
    for (const id of current) {
      if (!NEVER_OFFERED_MODELS.includes(id)) offered.add(id);
    }
  }
  return offered;
}

export function offeredModelsOf<T extends ListedModel>(
  models: readonly T[],
): T[] {
  const offered = offeredIdsOf(models);
  return models.filter((model) => offered.has(listingKey(model.id)));
}

export function rememberGatewayModels(models: readonly ListedModel[]): void {
  const current = listing();
  for (const model of models) {
    const key = listingKey(model.id);
    // A row from Django's task model list has fewer facts than a gateway row, so it never replaces one.
    if (current.models.get(key)?.family && !model.family) continue;
    current.models.set(key, model);
  }
  current.offered = offeredIdsOf([...current.models.values()]);
}

export function forgetGatewayModels(): void {
  const current = listing();
  current.models = new Map();
  current.offered = new Set();
}

export function knownGatewayModels(): ListedModel[] {
  return [...listing().models.values()];
}

export function listedModelFor(modelId: string): ListedModel | undefined {
  return listing().models.get(listingKey(modelId));
}

export function isOfferedModel(modelId: string): boolean {
  return listing().offered.has(listingKey(modelId));
}

export function isRetiredModel(modelId: string): boolean {
  const key = listingKey(modelId);
  return listing().models.has(key) && !listing().offered.has(key);
}

export function adapterForListedModel(model: ListedModel): Adapter | undefined {
  if (model.api_shapes?.length) {
    if (model.api_shapes.includes(ANTHROPIC_MESSAGES_SHAPE)) return "claude";
    if (model.api_shapes.includes(OPENAI_RESPONSES_SHAPE)) return "codex";
    return undefined;
  }
  return (Object.keys(PROVIDER_BY_RUNTIME_ADAPTER) as Adapter[]).find(
    (adapter) => PROVIDER_BY_RUNTIME_ADAPTER[adapter] === model.owned_by,
  );
}

function isAnthropicServed(modelId: string): boolean {
  return normalizeModelId(modelId).startsWith("claude-");
}

function effortsFromProvider(
  modelId: string,
  providerEfforts: readonly string[],
): ReasoningEffort[] {
  const efforts = REASONING_EFFORTS.filter(
    (effort) => effort !== "ultracode" && providerEfforts.includes(effort),
  );
  return providerEfforts.includes("xhigh") && isAnthropicServed(modelId)
    ? [...efforts, "ultracode"]
    : efforts;
}

export function reasoningEffortsForModel(
  adapter: Adapter,
  modelId: string,
): readonly ReasoningEffort[] {
  const listed = listedModelFor(modelId);
  if (!listed || adapterForListedModel(listed) !== adapter) return [];
  return effortsFromProvider(listed.id, listed.reasoning_efforts ?? []);
}

export function takesReasoningEffort(
  adapter: Adapter,
  modelId: string,
  effort: string,
): effort is ReasoningEffort {
  const listed = listedModelFor(modelId);
  if (listed && adapterForListedModel(listed) !== adapter) return false;
  if (listed?.reasoning_efforts) {
    return effortsFromProvider(listed.id, listed.reasoning_efforts).some(
      (taken) => taken === effort,
    );
  }
  return effortsFromProvider(modelId, REASONING_EFFORTS).some(
    (taken) =>
      taken === effort && (adapter === "claude" || taken !== "ultracode"),
  );
}

export const MODEL_ACCESS_FLAGS: readonly string[] = [
  ...new Set(Object.values(MODEL_FAMILY_ACCESS_FLAGS)),
];

export function accessFlagForModel(modelId: string): string | undefined {
  const listed = listedModelFor(modelId);
  return listed ? MODEL_FAMILY_ACCESS_FLAGS[familyOf(listed)] : undefined;
}

export function listedName(model: ListedModel | undefined): string | undefined {
  const name = model?.name;
  if (!name) return undefined;
  return name.endsWith(ALIAS_NAME_SUFFIX)
    ? name.slice(0, -ALIAS_NAME_SUFFIX.length)
    : name;
}

export function labelForModel(modelId: string): string | undefined {
  return listedName(listedModelFor(modelId));
}

export function supports1MContext(modelId: string): boolean {
  const window = listedModelFor(modelId)?.context_window ?? 0;
  return isAnthropicServed(modelId) && window >= LONG_CONTEXT_WINDOW;
}

export function supportsFastMode(modelId: string): boolean {
  const listed = listedModelFor(modelId);
  return (
    listed !== undefined && FAST_MODE_MODEL_FAMILIES.includes(familyOf(listed))
  );
}

export function costForModel(modelId: string): ModelCost | undefined {
  const listed = listedModelFor(modelId);
  if (!listed?.input_per_mtok || !listed.output_per_mtok) return undefined;
  return {
    inputPerMtok: listed.input_per_mtok,
    outputPerMtok: listed.output_per_mtok,
  };
}

function roundHalfEven(value: number, digits: number): number {
  const factor = 10 ** digits;
  const scaled = value * factor;
  const nearest = Math.round(scaled);
  const isHalf = Math.abs(scaled - Math.trunc(scaled)) === 0.5;
  return (isHalf && nearest % 2 !== 0 ? nearest - 1 : nearest) / factor;
}

function formatMultiplier(multiplier: number): string {
  if (multiplier >= 10) return String(roundHalfEven(multiplier, 0));
  if (multiplier >= 0.95) return String(roundHalfEven(multiplier, 1));
  return String(roundHalfEven(multiplier, 2));
}

export function costMultiplierLabel(
  cost: ModelCost,
  baseline: ModelCost,
): string {
  const inputRatio = cost.inputPerMtok / baseline.inputPerMtok;
  const outputRatio = cost.outputPerMtok / baseline.outputPerMtok;
  const spread =
    Math.abs(inputRatio - outputRatio) / Math.max(inputRatio, outputRatio);
  const multiplier = formatMultiplier((inputRatio + outputRatio) / 2);
  return `${spread > COST_RATIO_TOLERANCE ? "≈" : ""}${multiplier}×`;
}

export function formatCostRates(cost: ModelCost): string {
  const money = (amount: number): string =>
    Number.isInteger(amount) ? `$${amount}` : `$${amount.toFixed(2)}`;
  return `Input ${money(cost.inputPerMtok)} · Output ${money(cost.outputPerMtok)} per 1M tokens`;
}

export function costBaselineLabel(): string | undefined {
  return labelForModel(COST_BASELINE_MODEL);
}

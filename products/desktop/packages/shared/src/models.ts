import type { Adapter } from "./adapter";

/**
 * Returns the id unless it's a premium family (currently Fable) that must be
 * an explicit per-task pick and never the implicit default for a new task.
 */
export function defaultEligibleModel(
  modelId: string | null | undefined,
): string | undefined {
  if (!modelId) return undefined;
  const family = modelId.toLowerCase().split("/").pop() ?? "";
  return family.startsWith("claude-fable") ? undefined : modelId;
}

/**
 * ACP SessionConfigSelectOption `_meta` key for the free-tier model gate:
 * adapters mark models the caller's org can't use so pickers render them
 * locked behind an upgrade gate instead of omitting them.
 */
const RESTRICTED_MODEL_META_KEY = "posthog.code/restrictedModel";

/**
 * ACP SessionConfigSelectOption `_meta` key for a model outside the gateway
 * catalog. Picker code uses this explicit mark to render the option without a
 * cost chip.
 */
const CUSTOM_MODEL_META_KEY = "posthog.code/customModel";

export function customModelMeta(): Record<string, unknown> {
  return { [CUSTOM_MODEL_META_KEY]: true };
}

export function isCustomModelOption(
  meta: Record<string, unknown> | null | undefined,
): boolean {
  return meta?.[CUSTOM_MODEL_META_KEY] === true;
}

export function restrictedModelMeta(): Record<string, unknown> {
  return { [RESTRICTED_MODEL_META_KEY]: true };
}

export function isRestrictedModelOption(
  meta: Record<string, unknown> | null | undefined,
): boolean {
  return meta?.[RESTRICTED_MODEL_META_KEY] === true;
}

/**
 * ACP SessionConfigSelectOption `_meta` key marking the adapter's default
 * value for a select option, so pickers can render a "Default" badge.
 */
export const DEFAULT_OPTION_META_KEY = "posthog.code/defaultOption";

/**
 * ACP SessionConfigSelectOption `_meta` key carrying a documentation URL for
 * an option value, so pickers can render a help affordance linking to it.
 */
export const OPTION_DOCS_URL_META_KEY = "posthog.code/docsUrl";

export function isDefaultSelectOption(
  meta: Record<string, unknown> | null | undefined,
): boolean {
  return meta?.[DEFAULT_OPTION_META_KEY] === true;
}

export function selectOptionDocsUrl(
  meta: Record<string, unknown> | null | undefined,
): string | undefined {
  const url = meta?.[OPTION_DOCS_URL_META_KEY];
  return typeof url === "string" ? url : undefined;
}

/**
 * ACP SessionConfigSelectOption `_meta` key naming the harness a model runs
 * on, so a picker offering models across harnesses can switch to the right
 * one when a cross-harness model is chosen.
 */
const MODEL_HARNESS_META_KEY = "posthog.code/modelHarness";

export function modelHarnessMeta(adapter: Adapter): Record<string, unknown> {
  return { [MODEL_HARNESS_META_KEY]: adapter };
}

export function selectOptionHarness(
  meta: Record<string, unknown> | null | undefined,
): Adapter | undefined {
  const harness = meta?.[MODEL_HARNESS_META_KEY];
  return harness === "claude" || harness === "codex" ? harness : undefined;
}

/**
 * Gateway models the Pi harness can still run, but that no picker offers:
 * retired or superseded ids. The provider keeps them runnable so a session
 * pinned to one still starts, which means every list a person picks from must
 * filter them out here.
 */
const HIDDEN_PI_MODEL_IDS = new Set([
  "claude-sonnet-4-5",
  "claude-sonnet-4-6",
  "claude-sonnet-4-7",
  "claude-sonnet-4-8",
  "claude-opus-4-5",
  "claude-opus-4-6",
  "claude-opus-4-7",
  "claude-opus-4-8",
  "gpt-5.2",
  "gpt-5.3-codex",
  "gpt-5.4",
  "gpt-5.5",
  "gpt-5-mini",
  "@cf/zai-org/glm-5.2",
]);

export function isHiddenPiModelId(modelId: string): boolean {
  return HIDDEN_PI_MODEL_IDS.has(modelId);
}

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
export const RESTRICTED_MODEL_META_KEY = "posthog.code/restrictedModel";

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

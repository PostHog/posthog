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

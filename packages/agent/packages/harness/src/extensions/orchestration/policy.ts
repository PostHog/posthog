/**
 * Enforces `settings.subagents.modelScope` (an allow-list of model glob
 * patterns) before a subagent is allowed to spawn against a given model.
 */
import type { ModelScopeConfig } from "./settings";

export class SubagentPolicyError extends Error {}

function patternToRegExp(pattern: string): RegExp {
  const escaped = pattern
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, ".*");
  return new RegExp(`^${escaped}$`);
}

export function matchesAllowList(modelKey: string, allow: string[]): boolean {
  return allow.some((pattern) => patternToRegExp(pattern).test(modelKey));
}

export interface ModelScopeCheck {
  allowed: boolean;
  enforced: boolean;
  reason?: string;
}

/**
 * Checks `modelKey` ("provider/id") against `modelScope`. When there's no
 * `allow` list configured, everything is allowed regardless of `enforce`.
 */
export function checkModelScope(
  modelKey: string,
  modelScope: ModelScopeConfig | undefined,
): ModelScopeCheck {
  const allow = modelScope?.allow;
  if (!allow || allow.length === 0)
    return { allowed: true, enforced: Boolean(modelScope?.enforce) };

  const allowed = matchesAllowList(modelKey, allow);
  return {
    allowed,
    enforced: Boolean(modelScope?.enforce),
    reason: allowed
      ? undefined
      : `Model "${modelKey}" is not in the configured modelScope.allow list (${allow.join(", ")}).`,
  };
}

/**
 * Throws `SubagentPolicyError` when `modelScope.enforce` is set and the model
 * is disallowed. Otherwise returns a warning message (or `undefined`) for the
 * caller to surface non-fatally.
 */
export function applyModelScope(
  modelKey: string,
  modelScope: ModelScopeConfig | undefined,
): string | undefined {
  const check = checkModelScope(modelKey, modelScope);
  if (check.allowed) return undefined;
  if (check.enforced) throw new SubagentPolicyError(check.reason);
  return check.reason;
}

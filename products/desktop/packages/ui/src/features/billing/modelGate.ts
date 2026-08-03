import type { SessionConfigSelectOption } from "@agentclientprotocol/sdk";
import { isRestrictedModelOption } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "../../shell/analytics";
import { useUsageLimitStore } from "./usageLimitStore";

/** Whether a picker option is outside the org's plan (free-tier model gate). */
export function isRestrictedModel(
  option: Pick<SessionConfigSelectOption, "_meta">,
): boolean {
  return isRestrictedModelOption(option._meta ?? undefined);
}

/**
 * Intercepts a pick of a plan-restricted model: opens the upgrade gate and
 * returns true so the caller skips the selection.
 */
export function gateRestrictedModelPick(
  options: SessionConfigSelectOption[],
  value: string,
): boolean {
  const picked = options.find((opt) => opt.value === value);
  if (!picked || !isRestrictedModel(picked)) return false;
  track(ANALYTICS_EVENTS.UPGRADE_PROMPT_SHOWN, {
    surface: "model_picker",
    cause: "model_gate",
  });
  useUsageLimitStore.getState().show({ cause: "model_gate" });
  return true;
}

import type { ContentBlock } from "@agentclientprotocol/sdk";
import type { ExecutionMode, PermissionRequest } from "@posthog/shared";

/** Option ids offered when approving ExitPlanMode (see buildExitPlanModePermissionOptions). */
export const PLAN_APPROVAL_ACCEPT_OPTION_IDS = [
  "auto",
  "default",
  "acceptEdits",
  "bypassPermissions",
] as const;

export type PlanApprovalAcceptOptionId =
  (typeof PLAN_APPROVAL_ACCEPT_OPTION_IDS)[number];

/**
 * Opt-in plan-approval option: clear planning context, then continue from the
 * approved plan. Kept in sync with `CLEAR_AND_CONTINUE_OPTION_ID` in the Claude
 * permission-options module (agent cannot import core).
 */
export const CLEAR_AND_CONTINUE_OPTION_ID = "clearAndContinue";

/** Answers key used by the plan UI to carry the ModeSelector choice. */
export const CLEAR_AND_CONTINUE_EXECUTION_MODE_KEY = "executionMode";

export function isPlanApprovalPermission(
  permission: PermissionRequest,
): boolean {
  return permission.toolCall?.kind === "switch_mode";
}

export function isPlanApprovalAcceptOption(
  optionId: string,
): optionId is PlanApprovalAcceptOptionId {
  return (PLAN_APPROVAL_ACCEPT_OPTION_IDS as readonly string[]).includes(
    optionId,
  );
}

export function isClearAndContinueOption(optionId: string): boolean {
  return optionId === CLEAR_AND_CONTINUE_OPTION_ID;
}

/**
 * Only the explicit "clear history and continue from plan" option triggers a
 * fresh implementation session — normal approve keeps the planning context.
 */
export function shouldContinueFromApprovedPlan(
  permission: PermissionRequest,
  optionId: string,
): boolean {
  return (
    isPlanApprovalPermission(permission) && isClearAndContinueOption(optionId)
  );
}

export function extractPlanMarkdownFromPermission(
  permission: PermissionRequest,
): string | null {
  const rawInput = permission.toolCall?.rawInput as
    | { plan?: unknown }
    | undefined;
  const plan = rawInput?.plan;
  if (typeof plan !== "string") return null;
  const trimmed = plan.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function toApprovedExecutionMode(
  optionId: PlanApprovalAcceptOptionId,
): ExecutionMode {
  return optionId;
}

export function resolveClearAndContinueExecutionMode(
  answers?: Record<string, string>,
): ExecutionMode {
  const mode = answers?.[CLEAR_AND_CONTINUE_EXECUTION_MODE_KEY];
  if (mode && isPlanApprovalAcceptOption(mode)) {
    return toApprovedExecutionMode(mode);
  }
  return "default";
}

export function buildApprovedPlanContinuationPrompt(
  planMarkdown: string,
): ContentBlock[] {
  const text = [
    "The user approved the implementation plan below. Planning is complete — execute this plan directly.",
    "Do not re-enter plan mode unless the user asks for a significant change in direction.",
    "",
    planMarkdown,
  ].join("\n");
  return [{ type: "text", text }];
}

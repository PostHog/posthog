import type {
  RequestPermissionRequest,
  RequestPermissionResponse,
} from "@agentclientprotocol/sdk";

/**
 * The no-user-available contract: the model must surface the question as regular
 * assistant text and end its turn instead of guessing an answer.
 *
 * AgentServer's background-mode branch has its own copy of this that ends "so the
 * user can answer when they are back", which fits a cloud task someone returns
 * to. Keep them in sync when the instructions change.
 */
const UNATTENDED_QUESTION_MESSAGE =
  "No user is available to answer this question. Do NOT pick an answer yourself " +
  "and do NOT re-ask via this tool. Restate the question and its options in your " +
  "response, then end your turn.";

/**
 * Resolves a permission request for a host with no user to ask: question tool
 * calls are parked, everything else that reaches the client is auto-approved.
 *
 * Prefers `allow_once` so an unattended run never persists allow-always rules
 * into the target repository's settings, and a reject-only request resolves to
 * `reject_once` rather than whatever option happens to be listed first. Plan
 * approvals are the exception, see below.
 *
 * Two other unattended policies exist and behave differently: AgentServer's
 * cloud branch and `buildAutoApproveOutcome` in `@posthog/workspace-server` both
 * take the first allow option in array order, and neither prefers `reject_once`.
 * This is the intended behavior for all three; adopting it there is a follow-up.
 */
export function resolveUnattendedPermissionRequest(
  params: RequestPermissionRequest,
): RequestPermissionResponse {
  if (params.toolCall._meta?.codeToolKind === "question") {
    return {
      outcome: { outcome: "cancelled" },
      _meta: { message: UNATTENDED_QUESTION_MESSAGE },
    };
  }

  const { options } = params;

  // A plan approval's options are session modes, not degrees of consent, and its
  // only allow_once is "manually approve edits". Preferring kind there would
  // switch an unattended run into an interactive mode and persist that into the
  // repo's local settings. The adapter puts the current mode first, so take
  // array order and carry on in the mode the caller asked for.
  const chosen =
    params.toolCall.kind === "switch_mode"
      ? (options.find(
          (o) => o.kind === "allow_once" || o.kind === "allow_always",
        ) ?? options[0])
      : (options.find((o) => o.kind === "allow_once") ??
        options.find((o) => o.kind === "allow_always") ??
        options.find((o) => o.kind === "reject_once") ??
        options[0]);
  if (!chosen) {
    return { outcome: { outcome: "cancelled" } };
  }
  return { outcome: { outcome: "selected", optionId: chosen.optionId } };
}

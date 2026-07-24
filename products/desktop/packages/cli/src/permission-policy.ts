import type {
  RequestPermissionRequest,
  RequestPermissionResponse,
} from "@agentclientprotocol/sdk";

/**
 * Mirrors the cloud background-mode reply: the model must surface the question
 * as regular assistant text and end its turn instead of guessing an answer.
 */
const UNATTENDED_QUESTION_MESSAGE =
  "No user is available to answer this question. Do NOT pick an answer yourself " +
  "and do NOT re-ask via this tool. Restate the question and its options in your " +
  "response, then end your turn.";

/**
 * Unattended permission policy. Question tool calls are parked (no user to
 * answer); everything else that reaches the client is auto-approved. Prefers
 * allow_once so a one-shot run never persists allow-always rules into the
 * target repository's settings.
 */
export function resolvePermissionRequest(
  params: RequestPermissionRequest,
): RequestPermissionResponse {
  const meta = params.toolCall?._meta as { codeToolKind?: string } | undefined;
  if (meta?.codeToolKind === "question") {
    return {
      outcome: { outcome: "cancelled" },
      _meta: { message: UNATTENDED_QUESTION_MESSAGE },
    };
  }

  const options = params.options ?? [];
  const chosen =
    options.find((o) => o.kind === "allow_once") ??
    options.find((o) => o.kind === "allow_always") ??
    options[0];
  if (!chosen) {
    return { outcome: { outcome: "cancelled" } };
  }
  return { outcome: { outcome: "selected", optionId: chosen.optionId } };
}

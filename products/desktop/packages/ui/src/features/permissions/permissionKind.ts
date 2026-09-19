import { QuestionMetaSchema } from "@posthog/agent/adapters/claude/questions/utils";
import { readMcpToolName } from "@posthog/shared";
import type { PermissionToolCall } from "./types";

/**
 * The kind a permission card dispatches on. The code harness reports a
 * `codeToolKind` that is finer than the ACP `kind`, so it wins where both
 * exist.
 */
export function readPermissionKind(
  toolCall: PermissionToolCall,
): string | undefined {
  const meta = toolCall._meta as { codeToolKind?: string } | undefined;
  return meta?.codeToolKind ?? toolCall.kind ?? undefined;
}

/** Whether the request is a plan waiting for approval. */
export function isPlanPermission(toolCall: PermissionToolCall): boolean {
  return readPermissionKind(toolCall) === "switch_mode";
}

/**
 * Whether the request is one the user reads before answering: an
 * implementation plan, or a set of choices. Those dock in the composer card,
 * where the thread stays one click away. Every other permission is a short
 * yes or no and keeps the compact dock below the thread.
 */
export function isComposerPanelPermission(
  toolCall: PermissionToolCall,
): boolean {
  // Mirrors `PermissionSelector`, which routes an MCP call to its own card
  // before it looks at the kind. The two must agree, or the panel would frame
  // a card that is not a plan or a question set.
  if (readMcpToolName(toolCall._meta)) return false;
  return isPlanPermission(toolCall) || readQuestionCount(toolCall) > 0;
}

/** How many questions a choice request carries, or 0 for anything else. */
export function readQuestionCount(toolCall: PermissionToolCall): number {
  const result = QuestionMetaSchema.safeParse(toolCall._meta);
  return result.success ? result.data.questions.length : 0;
}

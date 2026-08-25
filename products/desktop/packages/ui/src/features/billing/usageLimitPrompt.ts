import { classifyGatewayLimitError, getErrorMessage } from "@posthog/shared";
import { useUsageLimitStore } from "./usageLimitStore";

/**
 * Show the upgrade modal when `error` is a spend-gate block, so the user gets the
 * billing route instead of a toast that only names the limit. Returns false for
 * anything else, leaving the caller's own error handling to run.
 *
 * Use this on paths that receive an already-stringified failure — a saga result, a
 * rejected mutation, a run's error message — where the typed CloudUsageLimitError
 * has been reduced to prose.
 */
export function showUsageLimitPromptForError(error: unknown): boolean {
  // getErrorMessage only unwraps Error-shaped values; these paths often hand us the
  // bare string a saga or an API row already reduced the failure to.
  const message = typeof error === "string" ? error : getErrorMessage(error);
  const cause = classifyGatewayLimitError(message);
  if (!cause) return false;
  useUsageLimitStore.getState().show({ cause });
  return true;
}

import { requestErrorStatus } from "@posthog/api-client/fetcher";

/**
 * The backend gates the approvals endpoints behind an org-membership ADMIN
 * check and answers 404 (not 403) for non-admins, so a 404 from these
 * endpoints means "no permission". For the per-agent endpoint this only
 * holds when the application is known to exist — AgentApprovalsPane renders
 * inside AgentDetailLayout, which gates on the application having loaded.
 */
export function isApprovalsPermissionError(error: unknown): boolean {
  return requestErrorStatus(error) === 404;
}

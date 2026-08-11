import { requestErrorStatus } from "@posthog/api-client/fetcher";

/**
 * Why loading a task failed, to the resolution the UI actually acts on.
 *
 * `not_found` is the one case with a real next step for the user: the task id
 * is valid but this project cannot see it, which almost always means it lives
 * in another project (the id came from a push, a shared link, or a project
 * switch). Everything else — offline, DNS, 5xx, an expired token — is the same
 * "try again" story, so it stays one bucket.
 */
export type TaskLoadFailure = "not_found" | "other";

/**
 * Only an explicit 404 from the API counts as not-found. A network failure
 * never reaches the server, so it cannot tell us the task is missing —
 * classifying it as not-found would send the user off to hunt through their
 * projects for a task that is right where they left it.
 */
export function classifyTaskLoadError(error: unknown): TaskLoadFailure {
  return requestErrorStatus(error) === 404 ? "not_found" : "other";
}

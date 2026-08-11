import { paths } from "@/lib/deep-links";

export const DEFAULT_POST_LOGIN_ROUTE = paths.tasksTab;

/**
 * Where to land after a successful sign-in: the originally-requested deep
 * link if there was one, otherwise the default tab. Guards against `next`
 * pointing back at the auth flow (which would loop) or being a non-local URL.
 */
export function resolvePostLoginTarget(next: string | string[] | undefined) {
  return typeof next === "string" &&
    next.startsWith("/") &&
    !next.startsWith("/auth") &&
    !next.startsWith("/select-project")
    ? next
    : DEFAULT_POST_LOGIN_ROUTE;
}

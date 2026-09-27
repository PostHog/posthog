import type { LocalToolGateMeta } from "./registry";

export const DESKTOP_CLIENT_PROVENANCE = "posthog_desktop";

export function isDesktopTask(meta: LocalToolGateMeta | undefined): boolean {
  return (
    meta?.environment === "local" ||
    meta?.taskClientProvenance === DESKTOP_CLIENT_PROVENANCE
  );
}

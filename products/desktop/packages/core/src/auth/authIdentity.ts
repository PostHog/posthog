import { getCustomCloud } from "@posthog/shared";
import type { AuthState } from "./schemas";

export function getAuthIdentity(authState: AuthState): string | null {
  if (authState.status !== "authenticated" || !authState.cloudRegion) {
    return null;
  }
  // Every built-in region maps to one origin, but many instances share the
  // custom region, so the identity needs the instance to keep two custom
  // sessions from reading each other's persisted state.
  const scope =
    authState.cloudRegion === "custom"
      ? `custom:${customCloudHost() ?? "unset"}`
      : authState.cloudRegion;
  return `${scope}:${authState.currentProjectId ?? "none"}`;
}

function customCloudHost(): string | null {
  const url = getCustomCloud()?.url;
  if (!url) return null;
  try {
    return new URL(url).host;
  } catch {
    return null;
  }
}

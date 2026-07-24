import type { UserBasic } from "@posthog/shared/domain-types";

/**
 * Display name for a task/thread author's `UserBasic`, shared by the channel
 * feed and the thread panel. Avatar initials come from the app-wide
 * `getUserInitials` (`@posthog/ui/features/auth/userInitials`).
 */
export function userDisplayName(user: UserBasic | null | undefined): string {
  if (!user) return "Unknown";
  const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return name || user.email;
}

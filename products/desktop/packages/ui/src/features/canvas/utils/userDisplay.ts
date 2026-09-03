import type { UserLike } from "@posthog/core/auth/userInitials";

// Display name for a task/thread author, shared by the channel feed and the
// thread panel.
export function userDisplayName(user: UserLike | null | undefined): string {
  if (!user) return "Unknown";
  const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return name || user.email || "Unknown";
}

interface UserNameLike {
  first_name?: string | null;
  last_name?: string | null;
  email?: string | null;
}

/**
 * Display name for a task/thread author's `UserBasic` (or any leaner
 * person shape), shared by the channel feed and the thread panel. Avatar
 * initials come from the app-wide `getUserInitials`
 * (`@posthog/ui/features/auth/userInitials`).
 */
export function userDisplayName(user: UserNameLike | null | undefined): string {
  if (!user) return "Unknown";
  const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return name || user.email || "Unknown";
}

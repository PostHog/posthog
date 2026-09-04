import type { UserBasic } from "@posthog/shared/domain-types";

export function userDisplayName(user: UserBasic): string {
  const name = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return name || user.email;
}

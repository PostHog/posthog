import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";

export const ORGANIZATION_ADMIN_LEVEL = 8;

export function useIsOrgAdmin(): { isAdmin: boolean | null } {
  const client = useOptionalAuthenticatedClient();
  const { data, isLoading } = useCurrentUser({ client });
  const level = data?.organization?.membership_level ?? null;
  if (isLoading || level === null) return { isAdmin: null };
  return { isAdmin: level >= ORGANIZATION_ADMIN_LEVEL };
}

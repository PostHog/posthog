import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { getPostHogUrl } from "@posthog/ui/utils/urls";

/**
 * The current organization's name and logo, for Home's hero. Logos aren't in
 * the auth state's project map, so this cross-references the user's org list —
 * the same route the project switcher takes.
 */
export function useHomeOrg(): { orgName: string | null; logoSrc?: string } {
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const currentOrgId = useAuthStateValue((state) => state.currentOrgId);

  const organization =
    currentUser?.organizations?.find((org) => org.id === currentOrgId) ?? null;
  if (!organization) return { orgName: null };

  return {
    orgName: organization.name,
    logoSrc: organization.logo_media_id
      ? (getPostHogUrl(`/uploaded_media/${organization.logo_media_id}`) ??
        undefined)
      : undefined,
  };
}

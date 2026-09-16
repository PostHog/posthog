import { isNotAuthenticatedError } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  AUTH_SCOPED_QUERY_META,
  useCurrentUser,
} from "@posthog/ui/features/auth/useCurrentUser";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

export type OrgConsent =
  | { status: "loading"; organizationId?: string }
  | {
      status: "error";
      organizationId?: string;
      retry: () => Promise<void>;
    }
  | {
      status: "resolved";
      organizationId: string;
      needsAiConsent: boolean;
      needsBetaTerms: boolean;
      satisfied: boolean;
      retry: () => Promise<void>;
    };

export const desktopBetaTermsKeys = {
  all: () => ["auth", "desktop-beta-terms"] as const,
  acceptance: (projectId: number | null) =>
    [...desktopBetaTermsKeys.all(), projectId] as const,
};

function useDesktopBetaTerms(
  organizationId: string | undefined,
  projectId: number | null,
  enabled = true,
) {
  const client = useOptionalAuthenticatedClient();
  return useQuery({
    queryKey: desktopBetaTermsKeys.acceptance(projectId),
    queryFn: async () => {
      if (!client || projectId === null) throw new Error("Not authenticated");
      return await client.areDesktopBetaTermsAccepted(projectId);
    },
    enabled: enabled && !!client && !!organizationId && projectId !== null,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: "always",
    meta: AUTH_SCOPED_QUERY_META,
  });
}

export function useOrgConsent(enabled = true): OrgConsent {
  const client = useOptionalAuthenticatedClient();
  const currentUserQuery = useCurrentUser({
    client,
    enabled,
    refetchOnWindowFocus: "always",
  });
  const organization = currentUserQuery.data?.organization;
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const betaTermsQuery = useDesktopBetaTerms(
    organization?.id,
    projectId,
    enabled,
  );
  const queryClient = useQueryClient();
  const retry = useCallback(async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: ["auth"] });
  }, [queryClient]);

  const reportableError = [currentUserQuery.error, betaTermsQuery.error].some(
    (error) => error != null && !isNotAuthenticatedError(error),
  );
  if (reportableError) {
    return { status: "error", organizationId: organization?.id, retry };
  }
  if (!organization || betaTermsQuery.data === undefined) {
    return { status: "loading", organizationId: organization?.id };
  }

  const needsAiConsent = organization.is_ai_data_processing_approved !== true;
  const needsBetaTerms = !betaTermsQuery.data;
  return {
    status: "resolved",
    organizationId: organization.id,
    needsAiConsent,
    needsBetaTerms,
    satisfied: !needsAiConsent && !needsBetaTerms,
    retry,
  };
}

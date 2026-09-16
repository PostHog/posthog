import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useUserQuery } from "@/features/auth/hooks/useUserQuery";
import { useAuthStore } from "@/features/auth/stores/authStore";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { deriveOrgConsent, type OrgConsent } from "../consentState";

export type OrgConsentResult = OrgConsent & { retry: () => void };

export const desktopBetaTermsKeys = {
  all: () => ["consent", "desktop-beta-terms"] as const,
  // Keyed on the project, because a token refresh can move the project while
  // the organization from /api/users/@me/ stays put.
  acceptance: (projectId: number | null) =>
    [...desktopBetaTermsKeys.all(), projectId] as const,
};

export function useDesktopBetaTerms(organizationId: string | undefined) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const projectId = useAuthStore((s) => s.projectId);
  return useQuery({
    queryKey: desktopBetaTermsKeys.acceptance(projectId),
    queryFn: () => {
      if (projectId === null) throw new Error("No project");
      return getPostHogApiClient().areDesktopBetaTermsAccepted(projectId);
    },
    enabled: isAuthenticated && !!organizationId && projectId !== null,
    staleTime: 5 * 60 * 1000,
  });
}

export function useOrgConsent(): OrgConsentResult {
  const userQuery = useUserQuery();
  const organization = userQuery.data?.organization;
  const betaTermsQuery = useDesktopBetaTerms(organization?.id);
  const queryClient = useQueryClient();

  const retry = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["user"] });
    void queryClient.invalidateQueries({
      queryKey: desktopBetaTermsKeys.all(),
    });
  }, [queryClient]);

  const consent = deriveOrgConsent({
    organization,
    betaTermsAccepted: betaTermsQuery.data,
    hasError: userQuery.isError || betaTermsQuery.isError,
  });

  return { ...consent, retry };
}

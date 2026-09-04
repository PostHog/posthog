import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useUserQuery } from "@/features/auth/hooks/useUserQuery";
import { useAuthStore } from "@/features/auth/stores/authStore";
import { getPostHogApiClient } from "@/lib/posthogApiClient";
import { deriveOrgConsent, type OrgConsent } from "../consentState";

export type OrgConsentResult = OrgConsent & { retry: () => void };

export const desktopBetaTermsKeys = {
  all: () => ["consent", "desktop-beta-terms"] as const,
  acceptance: (organizationId: string) =>
    [...desktopBetaTermsKeys.all(), organizationId] as const,
};

export function useDesktopBetaTerms(organizationId: string | undefined) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  return useQuery({
    queryKey: desktopBetaTermsKeys.acceptance(organizationId ?? "unknown"),
    queryFn: () => {
      if (!organizationId) throw new Error("No organization");
      return getPostHogApiClient().areDesktopBetaTermsAccepted(organizationId);
    },
    enabled: isAuthenticated && !!organizationId,
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

import { useHostTRPCClient } from "@posthog/host-router/react";
import { USAGE_QUERY_KEY } from "@posthog/ui/features/billing/useUsage";
import {
  identifyUser,
  resetUser,
  setUserGroups,
} from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useOptionalAuthenticatedClient } from "./authClient";
import {
  type AuthState,
  clearAuthScopedQueries,
  getAuthIdentity,
  refreshAuthStateQuery,
  useAuthStateValue,
  useCurrentUser,
} from "./authQueries";
import { useAuthUiStateStore } from "./authUiStateStore";

const log = logger.scope("auth-session");

function useAuthSubscriptionSync(): void {
  const hostClient = useHostTRPCClient();
  useEffect(() => {
    const subscription = hostClient.auth.onStateChanged.subscribe(undefined, {
      onData: () => {
        void refreshAuthStateQuery();
      },
      onError: (error) => {
        log.error("Auth state subscription error", { error });
      },
    });

    return () => subscription.unsubscribe();
  }, [hostClient]);
}

function useAuthIdentitySync(authState: AuthState): void {
  const authIdentity = getAuthIdentity(authState);
  const cloudRegion = authState.cloudRegion;
  const hostClient = useHostTRPCClient();
  useEffect(() => {
    if (!authIdentity) {
      if (!authState.bootstrapComplete || authState.status === "restoring") {
        return;
      }
      resetUser();
      void hostClient.analytics.resetUser.mutate();
      clearAuthScopedQueries();
      if (cloudRegion) {
        useAuthUiStateStore.getState().setStaleRegion(cloudRegion);
      }
      return;
    }

    useAuthUiStateStore.getState().clearStaleRegion();
  }, [
    authIdentity,
    authState.bootstrapComplete,
    authState.status,
    cloudRegion,
    hostClient,
  ]);
}

function useAuthAnalyticsIdentity(
  authIdentity: string | null,
  authState: AuthState,
  currentUser: ReturnType<typeof useCurrentUser>["data"],
): void {
  const hostClient = useHostTRPCClient();
  useEffect(() => {
    if (!authIdentity || !currentUser) {
      return;
    }

    const distinctId = currentUser.distinct_id || currentUser.email;

    identifyUser(distinctId, {
      email: currentUser.email,
      uuid: currentUser.uuid,
      project_id: authState.currentProjectId?.toString() ?? "",
      region: authState.cloudRegion ?? "",
    });

    setUserGroups(currentUser);

    void hostClient.analytics.setUserId.mutate({
      userId: distinctId,
      properties: {
        email: currentUser.email,
        uuid: currentUser.uuid,
        project_id: authState.currentProjectId?.toString() ?? "",
        region: authState.cloudRegion ?? "",
      },
    });
  }, [
    authIdentity,
    authState.cloudRegion,
    authState.currentProjectId,
    currentUser,
    hostClient,
  ]);
}

export function useUsageIdentitySync(
  authIdentity: string | null,
  orgId: string | null,
): void {
  const queryClient = useQueryClient();
  // Usage is org-scoped billing data — drop the cached snapshot on any sign-in,
  // sign-out, region, or org switch so a new org never renders the previous
  // org's spend. authIdentity keys on region + project, which can stay constant
  // across an org switch (e.g. between two orgs with no selected project), so
  // depend on currentOrgId too — matching the host UsageMonitorService, which
  // keys its snapshot on currentOrgId. Without it, a post-switch refresh that
  // fails would leave the stale value cached.
  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run on identity/org change
  useEffect(() => {
    queryClient.removeQueries({ queryKey: USAGE_QUERY_KEY });
  }, [authIdentity, orgId, queryClient]);
}

export function useAuthSession() {
  const authState = useAuthStateValue((state) => state);
  const client = useOptionalAuthenticatedClient();
  const { data: currentUser } = useCurrentUser({ client });
  const authIdentity = getAuthIdentity(authState);

  useAuthSubscriptionSync();
  useAuthIdentitySync(authState);
  useAuthAnalyticsIdentity(authIdentity, authState, currentUser);
  useUsageIdentitySync(authIdentity, authState.currentOrgId);

  return {
    authState,
    isBootstrapped: authState.bootstrapComplete,
  };
}

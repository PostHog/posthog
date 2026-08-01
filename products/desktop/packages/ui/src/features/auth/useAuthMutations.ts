import { useService } from "@posthog/di/react";
import { useHostTRPCClient } from "@posthog/host-router/react";
import type { CloudRegion } from "@posthog/shared";
import { clearCapturedLogs } from "@posthog/ui/shell/logCapture";
import { useMutation } from "@tanstack/react-query";
import { clearAuthScopedQueries, refreshAuthStateQuery } from "./authQueries";
import { AUTH_SIDE_EFFECTS, type IAuthSideEffects } from "./identifiers";

export function useLoginMutation() {
  const hostClient = useHostTRPCClient();
  const fx = useService<IAuthSideEffects>(AUTH_SIDE_EFFECTS);
  return useMutation({
    mutationFn: (region: CloudRegion) =>
      hostClient.auth.login.mutate({ region }).then((r) => r.state),
    onSuccess: (state, region) =>
      fx.onAuthSuccess(region, state.currentProjectId),
  });
}

export function useSignupMutation() {
  const hostClient = useHostTRPCClient();
  const fx = useService<IAuthSideEffects>(AUTH_SIDE_EFFECTS);
  return useMutation({
    mutationFn: (region: CloudRegion) =>
      hostClient.auth.signup.mutate({ region }).then((r) => r.state),
    onSuccess: (state, region) =>
      fx.onAuthSuccess(region, state.currentProjectId),
  });
}

export function useSelectProjectMutation() {
  const hostClient = useHostTRPCClient();
  const fx = useService<IAuthSideEffects>(AUTH_SIDE_EFFECTS);
  return useMutation({
    mutationFn: (projectId: number) => {
      fx.beforeProjectSwitch();
      return hostClient.auth.selectProject.mutate({ projectId });
    },
    onSuccess: () => fx.onProjectSelected(),
  });
}

export function useSwitchOrgMutation() {
  const hostClient = useHostTRPCClient();
  const fx = useService<IAuthSideEffects>(AUTH_SIDE_EFFECTS);
  return useMutation({
    mutationFn: (orgId: string) => {
      fx.beforeProjectSwitch();
      return hostClient.auth.switchOrg.mutate({ orgId });
    },
    onSuccess: async () => {
      clearAuthScopedQueries();
      await refreshAuthStateQuery();
    },
  });
}

export function useRedeemInviteCodeMutation() {
  const hostClient = useHostTRPCClient();
  return useMutation({
    mutationFn: (code: string) =>
      hostClient.auth.redeemInviteCode.mutate({ code }),
  });
}

export function useLogoutMutation() {
  const hostClient = useHostTRPCClient();
  const fx = useService<IAuthSideEffects>(AUTH_SIDE_EFFECTS);
  return useMutation({
    mutationFn: async () => {
      const previous = await hostClient.auth.getState.query();
      await hostClient.auth.logout.mutate();
      return previous;
    },
    onSuccess: (previous) => {
      // Privacy boundary: error bundles must never export another account's logs.
      clearCapturedLogs();
      fx.onLogout(previous.cloudRegion);
    },
  });
}

import type { GithubConnectService } from "@posthog/core/onboarding/githubConnectService";
import { GITHUB_CONNECT_SERVICE } from "@posthog/core/onboarding/identifiers";
import { useService } from "@posthog/di/react";
import { invalidateGithubQueries } from "@posthog/ui/features/integrations/useGithubUserConnect";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";

interface DisconnectVariables {
  installationId: string;
  silent?: boolean;
}

interface UseGithubDisconnect {
  disconnect: (variables: DisconnectVariables) => void;
  isDisconnecting: boolean;
  reconnect: (
    installationId: string,
    connect: () => Promise<void>,
  ) => Promise<void>;
}

export function useGithubDisconnect(
  projectId: number | null,
): UseGithubDisconnect {
  const queryClient = useQueryClient();
  const service = useService<GithubConnectService>(GITHUB_CONNECT_SERVICE);

  const mutation = useMutation({
    mutationFn: async (variables: DisconnectVariables) => {
      await service.disconnectInstallation(variables.installationId);
      return { silent: variables.silent ?? false };
    },
    onSuccess: ({ silent }) => {
      invalidateGithubQueries(queryClient, projectId);
      if (!silent) toast.success("GitHub disconnected.");
    },
    onError: (e) => {
      toast.error(
        e instanceof Error ? e.message : "Failed to disconnect GitHub.",
      );
    },
  });

  const reconnect = async (
    installationId: string,
    connect: () => Promise<void>,
  ) => {
    await service.reconnectStaleInstallation(installationId, connect);
    invalidateGithubQueries(queryClient, projectId);
  };

  return {
    disconnect: mutation.mutate,
    isDisconnecting: mutation.isPending,
    reconnect,
  };
}

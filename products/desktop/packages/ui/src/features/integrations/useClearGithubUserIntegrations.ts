import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { userGithubIntegrationKeys } from "@posthog/core/integrations/repositoryKeys";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { invalidateGithubQueries } from "@posthog/ui/features/integrations/useGithubUserConnect";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";

type GithubIntegrationClient = Pick<
  PostHogAPIClient,
  "getGithubUserIntegrations" | "disconnectGithubUserIntegration"
>;

export async function clearGithubUserIntegrations(
  client: GithubIntegrationClient,
): Promise<number> {
  const integrations = await client.getGithubUserIntegrations();
  await Promise.all(
    integrations.map((integration) =>
      client.disconnectGithubUserIntegration(integration.installation_id),
    ),
  );
  return integrations.length;
}

export function useClearGithubUserIntegrations() {
  const client = useOptionalAuthenticatedClient();
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async () => {
      if (!client) throw new Error("Not authenticated");
      return clearGithubUserIntegrations(client);
    },
    onSuccess: (removedCount) => {
      queryClient.setQueryData(userGithubIntegrationKeys.list(), []);
      if (removedCount === 0) {
        toast.info("No GitHub integration found.");
      } else {
        toast.success("Removed GitHub integration");
      }
    },
    onError: (error) => {
      toast.error(
        error instanceof Error
          ? error.message
          : "Failed to remove GitHub integration.",
      );
    },
    onSettled: () => {
      invalidateGithubQueries(queryClient, projectId);
    },
  });
}

import { requestErrorStatus } from "@posthog/api-client/fetcher";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { GITHUB_INSTALL_REQUESTS_QUERY_KEY } from "@posthog/ui/features/integrations/useGithubInstallRequests";
import { toast } from "@posthog/ui/primitives/toast";
import { useMutation, useQueryClient } from "@tanstack/react-query";

export function useDismissGithubInstallRequest() {
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (requestId: string) => {
      if (!client) throw new Error("Not authenticated");
      try {
        await client.dismissGithubInstallRequest(requestId);
      } catch (error) {
        // Already gone server-side counts as dismissed.
        if (requestErrorStatus(error) !== 404) throw error;
      }
    },
    // A swallowed 404 resolves, so onError only fires for a real failure.
    onError: () => {
      toast.error("Couldn't dismiss the request. Try again.");
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: [...GITHUB_INSTALL_REQUESTS_QUERY_KEY],
      });
    },
  });
}

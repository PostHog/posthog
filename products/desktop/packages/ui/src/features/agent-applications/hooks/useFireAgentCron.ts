import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useMutation } from "@tanstack/react-query";

/**
 * Fires a cron trigger out-of-band. Returns the created session id so the caller
 * can jump straight to the run it kicked off.
 */
export function useFireAgentCron(idOrSlug: string, revisionId: string) {
  const client = useAuthenticatedClient();
  return useMutation<{ session_id: string }, Error, { cronName: string }>({
    mutationFn: ({ cronName }) =>
      client.fireAgentCron(idOrSlug, revisionId, cronName),
  });
}

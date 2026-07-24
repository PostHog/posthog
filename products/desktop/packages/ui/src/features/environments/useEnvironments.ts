import { useWorkspaceTRPC } from "@posthog/workspace-client/trpc";
import { useQuery } from "@tanstack/react-query";

export function useEnvironments(repoPath: string | null) {
  const trpc = useWorkspaceTRPC();
  return useQuery({
    ...trpc.environment.list.queryOptions({ repoPath: repoPath ?? "" }),
    enabled: !!repoPath,
  });
}

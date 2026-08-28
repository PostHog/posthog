import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";

export function useProjectQuery() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);

  return useAuthenticatedQuery(
    ["project", projectId],
    async (client) => {
      if (!projectId) {
        throw new Error("No project ID available");
      }
      const data = await client.getProject(projectId);
      return data;
    },
    {
      staleTime: 5 * 60 * 1000,
      enabled: !!projectId,
    },
  );
}

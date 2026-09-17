import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../auth/store";

/** The project's IANA timezone, or null while it is unknown. Scout cron schedules resolve in it. */
export function useProjectTimezone(): string | null {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const { data } = useAuthenticatedQuery<string | null>(
    ["project", "timezone", projectId],
    async (client) => {
      if (!projectId) return null;
      const project = await client.getProject(projectId);
      return project.timezone ?? null;
    },
    {
      enabled: !!projectId,
      staleTime: Number.POSITIVE_INFINITY,
      // "always" is what beats the infinite stale time; a plain focus refetch obeys it, and
      // would leave a user who just changed the setting looking at the old timezone.
      refetchOnWindowFocus: "always",
    },
  );
  return data ?? null;
}

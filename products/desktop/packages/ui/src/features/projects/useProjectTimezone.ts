import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useAuthStateValue } from "../auth/store";

/**
 * The project's IANA timezone, or null while it is unknown. Scout cron schedules resolve in it,
 * so any surface that prints a clock time needs it to say which timezone that time is in.
 * A project changes timezone about never, so this is cached for the session.
 */
export function useProjectTimezone(): string | null {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const { data } = useAuthenticatedQuery<string | null>(
    ["project", "timezone", projectId],
    async (client) => {
      if (!projectId) return null;
      const project = await client.getProject(projectId);
      return project.timezone ?? null;
    },
    { enabled: !!projectId, staleTime: Number.POSITIVE_INFINITY },
  );
  return data ?? null;
}

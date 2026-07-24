import { deriveProjectsWithIntegrations } from "@posthog/core/onboarding/projectsWithIntegrations";
import { useQueries } from "@tanstack/react-query";
import { useMemo } from "react";
import { useOptionalAuthenticatedClient } from "../../auth/authClient";
import { useAuthStateFetched } from "../../auth/store";
import { AUTH_SCOPED_QUERY_META } from "../../auth/useCurrentUser";
import type { Integration } from "../../integrations/store";
import { useProjects } from "../../projects/useProjects";

export interface ProjectWithIntegrations {
  id: number;
  name: string;
  organization: { id: string; name: string };
  integrations: Integration[];
  hasGithubIntegration: boolean;
}

export function useProjectsWithIntegrations() {
  const { projects } = useProjects();
  const projectsLoading = !useAuthStateFetched();
  const client = useOptionalAuthenticatedClient();

  const integrationQueries = useQueries({
    queries: projects.map((project) => ({
      queryKey: ["integrations", project.id],
      queryFn: async () => {
        if (!client) throw new Error("Not authenticated");
        return client.getIntegrationsForProject(project.id);
      },
      enabled: !!client && projects.length > 0,
      staleTime: 60 * 1000,
      meta: AUTH_SCOPED_QUERY_META,
    })),
  });

  const isLoading =
    projectsLoading || integrationQueries.some((q) => q.isLoading);
  const isFetching = integrationQueries.some((q) => q.isFetching);

  const { projects: projectsWithIntegrations, projectsWithGithub } = useMemo(
    () =>
      deriveProjectsWithIntegrations(
        projects,
        integrationQueries.map((q) => q.data as Integration[] | undefined),
      ),
    [projects, integrationQueries],
  );

  return {
    projects: projectsWithIntegrations,
    projectsWithGithub,
    isLoading,
    isFetching,
  };
}

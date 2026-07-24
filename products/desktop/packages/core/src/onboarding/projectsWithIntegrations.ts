export interface OnboardingIntegration {
  kind: string;
  [key: string]: unknown;
}

export interface OnboardingProject {
  id: number;
  name: string;
  organization: { id: string; name: string };
}

export interface ProjectWithIntegrations<
  TIntegration extends OnboardingIntegration = OnboardingIntegration,
> {
  id: number;
  name: string;
  organization: { id: string; name: string };
  integrations: TIntegration[];
  hasGithubIntegration: boolean;
}

export function deriveProjectsWithIntegrations<
  TProject extends OnboardingProject,
  TIntegration extends OnboardingIntegration,
>(
  projects: TProject[],
  integrationsByIndex: (TIntegration[] | undefined)[],
): {
  projects: ProjectWithIntegrations<TIntegration>[];
  projectsWithGithub: ProjectWithIntegrations<TIntegration>[];
} {
  const projectsWithIntegrations = projects
    .map((project, index) => {
      const integrations = integrationsByIndex[index] ?? [];
      const hasGithubIntegration = integrations.some(
        (integration) => integration.kind === "github",
      );
      return {
        ...project,
        integrations,
        hasGithubIntegration,
      } as ProjectWithIntegrations<TIntegration>;
    })
    .sort((a, b) => a.name.localeCompare(b.name));

  const projectsWithGithub = projectsWithIntegrations.filter(
    (project) => project.hasGithubIntegration,
  );

  return { projects: projectsWithIntegrations, projectsWithGithub };
}

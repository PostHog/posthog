import type { Schemas } from "@posthog/api-client/generated";

export interface GitlabProjectsResult {
  integrationId: number;
  response: Schemas.GitLabProjectsResponse | undefined;
}

export interface CombinedGitlabProjects {
  /** Full project paths, in the order the integrations list them. */
  projects: string[];
  /** Which integration's token opens a project, keyed by lowercased path. */
  integrationIdByProject: Record<string, number>;
  /** Token scopes that coding tasks need and at least one connected token lacks. */
  missingScopes: string[];
}

/**
 * Merges the project lists of several GitLab integrations. A project that two
 * tokens can open keeps the first integration, so a task always names one.
 */
export function combineGitlabProjects(
  results: ReadonlyArray<GitlabProjectsResult>,
): CombinedGitlabProjects {
  const projects: string[] = [];
  const integrationIdByProject: Record<string, number> = {};
  const missingScopes = new Set<string>();
  for (const { integrationId, response } of results) {
    for (const scope of response?.missing_scopes ?? []) {
      missingScopes.add(scope);
    }
    for (const project of response?.projects ?? []) {
      const key = project.path_with_namespace.toLowerCase();
      if (key in integrationIdByProject) continue;
      integrationIdByProject[key] = integrationId;
      projects.push(project.path_with_namespace);
    }
  }
  return {
    projects,
    integrationIdByProject,
    missingScopes: [...missingScopes],
  };
}

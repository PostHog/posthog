import type { Schemas } from "@posthog/api-client/generated";
import type { Integration } from "./selectors";

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
 * Merges the project lists of several GitLab integrations. When two
 * connections list the same project, the task uses the one whose token has
 * every scope tasks need, else the first one listed.
 */
export function combineGitlabProjects(
  results: ReadonlyArray<GitlabProjectsResult>,
): CombinedGitlabProjects {
  const projects: string[] = [];
  const integrationIdByProject: Record<string, number> = {};
  const integrationsMissingScopes = new Set<number>();
  const missingScopes = new Set<string>();
  for (const { integrationId, response } of results) {
    const scopesMissing = response?.missing_scopes ?? [];
    if (scopesMissing.length > 0) {
      integrationsMissingScopes.add(integrationId);
    }
    for (const scope of scopesMissing) {
      missingScopes.add(scope);
    }
    for (const project of response?.projects ?? []) {
      const key = project.path_with_namespace.toLowerCase();
      const existing = integrationIdByProject[key];
      if (existing === undefined) {
        projects.push(project.path_with_namespace);
        integrationIdByProject[key] = integrationId;
      } else if (
        integrationsMissingScopes.has(existing) &&
        scopesMissing.length === 0
      ) {
        integrationIdByProject[key] = integrationId;
      }
    }
  }
  return {
    projects,
    integrationIdByProject,
    missingScopes: [...missingScopes],
  };
}

export interface GitlabProjectSelection {
  project: string;
  integrationId: number;
}

/**
 * The connection that covers `repository`, so a sidebar prefill can select a
 * GitLab project without listing projects. Each connection covers the single
 * project it was set up for.
 */
export function findGitlabProjectForRepository(
  repository: string | undefined,
  integrations: ReadonlyArray<Integration>,
): GitlabProjectSelection | null {
  const wanted = repository?.toLowerCase();
  if (!wanted) return null;
  for (const integration of integrations) {
    const project = integration.config?.path_with_namespace;
    if (typeof project === "string" && project.toLowerCase() === wanted) {
      return { project, integrationId: integration.id };
    }
  }
  return null;
}

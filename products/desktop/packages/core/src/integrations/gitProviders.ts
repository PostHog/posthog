import type { Integration } from "./selectors";

export const GIT_PROVIDER_KINDS = ["github", "gitlab"] as const;
export type GitProviderKind = (typeof GIT_PROVIDER_KINDS)[number];

/**
 * What PostHog Cloud can do for a provider today. The desktop reads these instead of checking
 * `provider === "github"` at each call site, so a backend endpoint added for GitLab turns one
 * capability on here and every surface follows.
 */
export interface GitProviderCapabilities {
  /** Repositories can be listed and searched page by page from the provider. */
  repositoryPicker: boolean;
  /** Branches of a repository can be listed. */
  branches: boolean;
  /** A connection owned by the signed-in user, not by the project. */
  personalConnections: boolean;
  /** Cloud tasks can clone the repository and open a pull or merge request. */
  cloudTasks: boolean;
}

/**
 * GitLab connections are the project-level ones Error tracking creates: one GitLab project per
 * connection, authenticated with a project access token. There is no repository, branch, or task
 * endpoint for them yet, so every GitLab capability stays off until the backend adds one.
 */
export const GIT_PROVIDER_CAPABILITIES: Record<
  GitProviderKind,
  GitProviderCapabilities
> = {
  github: {
    repositoryPicker: true,
    branches: true,
    personalConnections: true,
    cloudTasks: true,
  },
  gitlab: {
    repositoryPicker: false,
    branches: false,
    personalConnections: false,
    cloudTasks: false,
  },
};

export const GIT_PROVIDER_LABELS: Record<GitProviderKind, string> = {
  github: "GitHub",
  gitlab: "GitLab",
};

function isGitProviderKind(kind: string): kind is GitProviderKind {
  return (GIT_PROVIDER_KINDS as ReadonlyArray<string>).includes(kind);
}

export function enabledGitProviders(options: {
  gitlabEnabled: boolean;
}): GitProviderKind[] {
  return options.gitlabEnabled ? ["github", "gitlab"] : ["github"];
}

/** A project-level connection to one provider account, in a shape every provider shares. */
export interface GitProviderConnection {
  provider: GitProviderKind;
  integrationId: number;
  label: string;
}

/** A repository reachable through a connection. `fullName` is `owner/name` on GitHub and the full namespace path on GitLab. */
export interface GitProviderRepository {
  provider: GitProviderKind;
  integrationId: number;
  fullName: string;
  url: string;
}

function connectionLabel(integration: Integration): string {
  if (integration.display_name) return integration.display_name;
  const account = integration.config?.account?.name;
  if (account) return account;
  const path = integration.config?.path_with_namespace;
  if (typeof path === "string" && path) return path;
  return `${GIT_PROVIDER_LABELS[integration.kind as GitProviderKind]} ${integration.id}`;
}

export function gitProviderConnections(
  integrations: ReadonlyArray<Integration>,
  providers: ReadonlyArray<GitProviderKind>,
): GitProviderConnection[] {
  return integrations
    .filter(
      (integration): integration is Integration & { kind: GitProviderKind } =>
        isGitProviderKind(integration.kind) &&
        providers.includes(integration.kind),
    )
    .map((integration) => ({
      provider: integration.kind,
      integrationId: integration.id,
      label: connectionLabel(integration),
    }));
}

const GITLAB_DEFAULT_HOST = "https://gitlab.com";

function gitlabHost(integration: Integration): string {
  const hostname = integration.config?.hostname;
  if (typeof hostname !== "string" || !hostname.trim()) {
    return GITLAB_DEFAULT_HOST;
  }
  return hostname.trim().replace(/\/+$/, "");
}

/**
 * The one repository a GitLab connection reaches. The backend stores the project path when the
 * connection is created, so no request is needed to list it.
 */
export function gitlabRepository(
  integration: Integration,
): GitProviderRepository | null {
  const path = integration.config?.path_with_namespace;
  if (typeof path !== "string" || !path.trim()) return null;
  const fullName = path.trim().toLowerCase();
  return {
    provider: "gitlab",
    integrationId: integration.id,
    fullName,
    url: `${gitlabHost(integration)}/${fullName}`,
  };
}

export function githubRepositories(
  integrationId: number,
  fullNames: ReadonlyArray<string>,
): GitProviderRepository[] {
  return fullNames
    .map((name) => name.trim().toLowerCase())
    .filter((name) => name.length > 0)
    .map((fullName) => ({
      provider: "github" as const,
      integrationId,
      fullName,
      url: `https://github.com/${fullName}`,
    }));
}

export function sortGitProviderRepositories(
  repositories: ReadonlyArray<GitProviderRepository>,
): GitProviderRepository[] {
  return [...repositories].sort(
    (left, right) =>
      left.provider.localeCompare(right.provider) ||
      left.fullName.localeCompare(right.fullName),
  );
}

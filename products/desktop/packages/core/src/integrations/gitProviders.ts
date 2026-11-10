import type { Integration } from "./selectors";

export const GIT_PROVIDER_KINDS = ["github", "gitlab"] as const;
export type GitProviderKind = (typeof GIT_PROVIDER_KINDS)[number];

export interface GitProviderCapabilities {
  repositoryPicker: boolean;
  branches: boolean;
  personalConnections: boolean;
  cloudTasks: boolean;
}

// GitLab task and picker capabilities require backend support before they can be enabled.
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

import type {
  Integration,
  RepositoryOption,
  RepositorySelection,
  UserGithubIntegration,
} from "../types";

function getIntegrationLabel(integration: Integration): string {
  return (
    integration.display_name ??
    integration.config?.account?.login ??
    `GitHub ${integration.id}`
  );
}

export function buildRepositoryOptions(
  integrations: Integration[],
  repositoriesByIntegration: Record<number, string[]>,
): RepositoryOption[] {
  return integrations
    .flatMap((integration) =>
      (repositoriesByIntegration[integration.id] ?? []).map((repository) => ({
        integrationId: integration.id,
        integrationLabel: getIntegrationLabel(integration),
        repository,
      })),
    )
    .sort((left, right) => left.repository.localeCompare(right.repository));
}

export function buildUserRepositoryOptions(
  integrations: UserGithubIntegration[],
  repositoriesByInstallation: Record<string, string[]>,
): RepositoryOption[] {
  return integrations
    .flatMap((integration) =>
      (repositoriesByInstallation[integration.installation_id] ?? []).map(
        (repository) => ({
          integrationId: Number(integration.installation_id),
          integrationLabel:
            integration.account?.name ??
            `GitHub ${integration.installation_id}`,
          repository,
        }),
      ),
    )
    .sort((left, right) => left.repository.localeCompare(right.repository));
}

export function repositoryOptionsEqual(
  left: RepositoryOption[],
  right: RepositoryOption[],
): boolean {
  return (
    left.length === right.length &&
    left.every((option, index) => {
      const other = right[index];
      return (
        other?.integrationId === option.integrationId &&
        other.integrationLabel === option.integrationLabel &&
        other.repository === option.repository
      );
    })
  );
}

export function repositoryLoadWarning(
  failedCount: number,
  totalCount: number,
): string | null {
  if (failedCount === 0) return null;
  return failedCount === totalCount
    ? "Could not load GitHub repositories. Pull to retry."
    : "Some GitHub repositories could not be loaded. Pull to retry.";
}

export function findRepositoryOption(
  options: RepositoryOption[],
  selection: RepositorySelection,
): RepositoryOption | null {
  if (!selection.integrationId || !selection.repository) return null;
  return (
    options.find(
      (option) =>
        option.integrationId === selection.integrationId &&
        option.repository === selection.repository,
    ) ?? null
  );
}

export function toRepositorySelection(
  option: RepositoryOption | null,
): RepositorySelection {
  return {
    integrationId: option?.integrationId ?? null,
    repository: option?.repository ?? null,
  };
}

export function isRepositorySelectionComplete(
  selection: RepositorySelection,
): boolean {
  return !!selection.integrationId && !!selection.repository;
}

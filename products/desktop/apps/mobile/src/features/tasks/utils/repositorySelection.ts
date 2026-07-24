import type {
  Integration,
  RepositoryOption,
  RepositorySelection,
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
    .flatMap((integration) => {
      const repositories = repositoriesByIntegration[integration.id] ?? [];

      return repositories.map((repository) => ({
        integrationId: integration.id,
        integrationLabel: getIntegrationLabel(integration),
        repository,
      }));
    })
    .sort((left, right) => left.repository.localeCompare(right.repository));
}

export function findRepositoryOption(
  options: RepositoryOption[],
  selection: RepositorySelection,
): RepositoryOption | null {
  if (!selection.integrationId || !selection.repository) {
    return null;
  }

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

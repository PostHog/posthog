export const INTEGRATION_SERVICE = Symbol.for(
  "posthog.core.integrationService",
);

export const GITHUB_INTEGRATION_SERVICE = Symbol.for(
  "posthog.core.githubIntegrationService",
);

export const LINEAR_INTEGRATION_SERVICE = Symbol.for(
  "posthog.core.linearIntegrationService",
);

export const SLACK_INTEGRATION_SERVICE = Symbol.for(
  "posthog.core.slackIntegrationService",
);

export interface RepositoriesClient {
  refreshTeamRepository(integrationId: number): Promise<unknown>;
  refreshUserRepository(installationId: string): Promise<unknown>;
}

export const REPOSITORIES_CLIENT = Symbol.for(
  "posthog.core.repositoriesClient",
);

export const REPOSITORIES_SERVICE = Symbol.for(
  "posthog.core.repositoriesService",
);

export interface TeamFlowResult {
  success: boolean;
  error?: string;
}

export interface GithubConnectClient {
  startUserConnect(projectId: number): Promise<{ install_url: string }>;
  launchUrl(url: string): Promise<void>;
  startTeamFlow(input: {
    region: string;
    projectId: number;
  }): Promise<TeamFlowResult>;
}

export const GITHUB_CONNECT_CLIENT = Symbol.for(
  "posthog.core.integrations.githubConnectClient",
);

export const GITHUB_CONNECT_SERVICE = Symbol.for(
  "posthog.core.integrations.githubConnectService",
);

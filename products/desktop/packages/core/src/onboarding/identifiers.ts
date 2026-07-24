export interface GithubConnectClient {
  disconnectGithubUserIntegration(installationId: string): Promise<void>;
}

export const GITHUB_CONNECT_CLIENT = Symbol.for(
  "posthog.core.onboarding.githubConnectClient",
);

export const GITHUB_CONNECT_SERVICE = Symbol.for(
  "posthog.core.onboarding.githubConnectService",
);

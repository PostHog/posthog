export interface IntegrationAccount {
  name?: string;
  type?: string;
}

export interface IntegrationConfig {
  account?: IntegrationAccount;
  [key: string]: unknown;
}

export interface Integration {
  id: number;
  kind: string;
  config?: IntegrationConfig;
  display_name?: string;
  [key: string]: unknown;
}

export interface ClassifiedIntegrations {
  githubIntegrations: Integration[];
  hasGithubIntegration: boolean;
  slackIntegrations: Integration[];
  hasSlackIntegration: boolean;
}

export function classifyIntegrations(
  integrations: ReadonlyArray<Integration>,
): ClassifiedIntegrations {
  const githubIntegrations = integrations.filter((i) => i.kind === "github");
  const slackIntegrations = integrations.filter((i) => i.kind === "slack");

  return {
    githubIntegrations,
    hasGithubIntegration: githubIntegrations.length > 0,
    slackIntegrations,
    hasSlackIntegration: slackIntegrations.length > 0,
  };
}

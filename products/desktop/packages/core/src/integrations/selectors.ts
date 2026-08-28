export interface IntegrationAccount {
  name?: string;
  type?: string;
}

export interface IntegrationConfig {
  account?: IntegrationAccount;
  installation_id?: string | number;
  /** GitHub's scope for the installation: "all" repositories or "selected" ones. */
  repository_selection?: string | null;
  [key: string]: unknown;
}

export interface Integration {
  id: number;
  kind: string;
  config?: IntegrationConfig;
  display_name?: string;
  created_at?: string;
  /** GitHub only. False when disconnecting would also uninstall the App from GitHub. */
  installation_shared?: boolean | null;
  /** GitHub only. `unavailable` once the App was removed or suspended on GitHub. */
  installation_status?: "connected" | "unavailable" | null;
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

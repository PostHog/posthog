import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import { type SignalRecordKind, sourceNeedsFullRefresh } from "@posthog/shared";
import { inject, injectable } from "inversify";
import { LINEAR_OAUTH_FLOW, type LinearOAuthFlow } from "./identifiers";

type DataSourceType = "github" | "linear" | "jira" | "zendesk" | "pganalyze";

const REQUIRED_SCHEMAS: Record<DataSourceType, string[]> = {
  github: ["issues"],
  linear: ["issues"],
  jira: ["issues"],
  zendesk: ["tickets"],
  pganalyze: ["issues", "servers"],
};

const RECORD_KIND: Record<DataSourceType, SignalRecordKind> = {
  github: "issue",
  linear: "issue",
  jira: "issue",
  zendesk: "ticket",
  pganalyze: "issue",
};

const FULL_TABLE_REPLICATION = "full_refresh" as const;

/** Omitting the method leaves PostHog to pick the connector's declared cursor. */
function schemasPayload(source: DataSourceType) {
  const syncType = sourceNeedsFullRefresh(RECORD_KIND[source])
    ? { sync_type: FULL_TABLE_REPLICATION }
    : {};
  return REQUIRED_SCHEMAS[source].map((name) => ({
    name,
    should_sync: true,
    ...syncType,
  }));
}

const POLL_INTERVAL_MS = 3_000;
const POLL_TIMEOUT_MS = 300_000;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export interface GithubDataSourceParams {
  repository: string;
  githubIntegrationId: number;
}

export interface ZendeskDataSourceParams {
  subdomain: string;
  apiKey: string;
  email: string;
}

export interface PgAnalyzeDataSourceParams {
  apiKey: string;
  organizationSlug: string;
}

@injectable()
export class DataSourceService {
  constructor(
    @inject(LINEAR_OAUTH_FLOW)
    private readonly linearOAuth: LinearOAuthFlow,
  ) {}

  async createGithubDataSource(
    client: PostHogAPIClient,
    projectId: number,
    params: GithubDataSourceParams,
  ): Promise<void> {
    await client.createExternalDataSource(projectId, {
      source_type: "Github",
      payload: {
        repository: params.repository,
        auth_method: {
          selection: "oauth",
          github_integration_id: params.githubIntegrationId,
        },
        schemas: schemasPayload("github"),
      },
    });
  }

  async createLinearDataSource(
    client: PostHogAPIClient,
    projectId: number,
    linearIntegrationId: number | string,
  ): Promise<void> {
    await client.createExternalDataSource(projectId, {
      source_type: "Linear",
      payload: {
        linear_integration_id: linearIntegrationId,
        schemas: schemasPayload("linear"),
      },
    });
  }

  async createZendeskDataSource(
    client: PostHogAPIClient,
    projectId: number,
    params: ZendeskDataSourceParams,
  ): Promise<void> {
    await client.createExternalDataSource(projectId, {
      source_type: "Zendesk",
      payload: {
        subdomain: params.subdomain,
        api_key: params.apiKey,
        email_address: params.email,
        schemas: schemasPayload("zendesk"),
      },
    });
  }

  async createPgAnalyzeDataSource(
    client: PostHogAPIClient,
    projectId: number,
    params: PgAnalyzeDataSourceParams,
  ): Promise<void> {
    await client.createExternalDataSource(projectId, {
      source_type: "PgAnalyze",
      payload: {
        api_key: params.apiKey,
        organization_slug: params.organizationSlug,
        schemas: schemasPayload("pganalyze"),
      },
    });
  }

  async connectLinearAndAwaitIntegration(
    client: PostHogAPIClient,
    region: string,
    projectId: number,
    signal?: AbortSignal,
  ): Promise<number | string> {
    await this.linearOAuth.startFlow(region, projectId);

    const deadline = Date.now() + POLL_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (signal?.aborted) {
        throw new Error("Linear connection cancelled");
      }
      await delay(POLL_INTERVAL_MS);
      try {
        const integrations = await client.getIntegrationsForProject(projectId);
        const linear = integrations.find(
          (i: { kind: string }) => i.kind === "linear",
        ) as { id: number | string } | undefined;
        if (linear) {
          return linear.id;
        }
      } catch {}
    }

    throw new Error("Connection timed out. Please try again.");
  }
}

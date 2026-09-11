import type {
  GithubConnectClient,
  RepositoriesClient,
  TeamFlowResult,
} from "@posthog/core/integrations/identifiers";
import type { CloudRegion } from "@posthog/core/integrations/schemas";
import { resolveService } from "@posthog/di/container";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";

async function authedClient() {
  const client = await getAuthenticatedClient();
  if (!client) {
    throw new Error("Not authenticated");
  }
  return client;
}

export class UiRepositoriesClient implements RepositoriesClient {
  async refreshTeamRepository(integrationId: number): Promise<unknown> {
    return (await authedClient()).refreshGithubRepositories(integrationId);
  }

  async refreshUserRepository(installationId: string): Promise<unknown> {
    return (await authedClient()).refreshGithubUserRepositories(installationId);
  }
}

export class UiGithubConnectClient implements GithubConnectClient {
  async startUserConnect(projectId: number): Promise<{ install_url: string }> {
    return (await authedClient()).startGithubUserIntegrationConnect(projectId);
  }

  async launchUrl(url: string): Promise<void> {
    await resolveService<HostTrpcClient>(
      HOST_TRPC_CLIENT,
    ).os.openExternal.mutate({ url });
  }

  async startTeamFlow(input: {
    region: string;
    projectId: number;
  }): Promise<TeamFlowResult> {
    return resolveService<HostTrpcClient>(
      HOST_TRPC_CLIENT,
    ).githubIntegration.startFlow.mutate({
      region: input.region as CloudRegion,
      projectId: input.projectId,
    });
  }
}

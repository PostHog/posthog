import type { GithubConnectClient } from "@posthog/core/onboarding/identifiers";
import { getAuthenticatedClient } from "@posthog/ui/features/auth/authClientImperative";

async function authedClient() {
  const client = await getAuthenticatedClient();
  if (!client) {
    throw new Error("Not authenticated");
  }
  return client;
}

export class OnboardingGithubConnectClient implements GithubConnectClient {
  async disconnectGithubUserIntegration(installationId: string): Promise<void> {
    await (await authedClient()).disconnectGithubUserIntegration(
      installationId,
    );
  }
}

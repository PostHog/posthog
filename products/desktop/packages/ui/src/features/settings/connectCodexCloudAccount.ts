import type {
  CodexAuthTokens,
  PostHogAPIClient,
  UserCodexIntegration,
} from "@posthog/api-client/posthog-client";

export type CodexAccountClient = Pick<
  PostHogAPIClient,
  "connectCodexUserIntegration"
>;

export interface CodexCloudAuthFile {
  read(): Promise<CodexAuthTokens>;
  remove(): Promise<void>;
}

/**
 * Hands the local login to PostHog. PostHog rotates the refresh token on
 * connect, so the local file is stale afterwards and is deleted; a failed
 * connect leaves it in place for another try.
 */
export async function connectCodexCloudAccount(
  client: CodexAccountClient,
  authFile: CodexCloudAuthFile,
): Promise<UserCodexIntegration> {
  const tokens = await authFile.read();
  const integration = await client.connectCodexUserIntegration(tokens);
  await authFile.remove();
  return integration;
}

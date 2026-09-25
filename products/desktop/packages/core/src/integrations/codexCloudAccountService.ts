import type {
  CodexAuthTokens,
  PostHogAPIClient,
  UserCodexIntegration,
} from "@posthog/api-client/posthog-client";
import { inject, injectable } from "inversify";

export const CODEX_CLOUD_ACCOUNT_HOST = Symbol.for(
  "posthog.core.codexCloudAccountHost",
);
export const CODEX_CLOUD_ACCOUNT_SERVICE = Symbol.for(
  "posthog.core.codexCloudAccountService",
);

export interface CodexCloudTerminal {
  command: string;
  cwd: string;
  additionalEnv: Record<string, string>;
  unsetEnv: string[];
}

export interface CodexCloudAccountHost {
  prepare(attemptId: string): Promise<CodexCloudTerminal>;
  read(attemptId: string): Promise<CodexAuthTokens>;
  remove(attemptId: string): Promise<void>;
  finish(attemptId: string): Promise<void>;
  cancel(attemptId: string): Promise<void>;
}

export interface CodexCloudConnectResult {
  integration: UserCodexIntegration;
  /** A failed cleanup does not undo the accepted connection. */
  staleFileError: Error | null;
}

@injectable()
export class CodexCloudAccountService {
  private attemptId: string | null = null;
  private preparation: Promise<CodexCloudTerminal> | null = null;
  private connection: Promise<CodexCloudConnectResult> | null = null;

  constructor(
    @inject(CODEX_CLOUD_ACCOUNT_HOST)
    private readonly host: CodexCloudAccountHost,
  ) {}

  async begin(attemptId: string): Promise<CodexCloudTerminal> {
    if (this.attemptId !== null) {
      throw new Error(
        "Another ChatGPT login is in progress. Wait for it to finish.",
      );
    }
    this.attemptId = attemptId;
    this.preparation = this.host.prepare(attemptId);
    try {
      return await this.preparation;
    } catch (error) {
      this.attemptId = null;
      throw error;
    } finally {
      this.preparation = null;
    }
  }

  connect(
    attemptId: string,
    client: Pick<PostHogAPIClient, "connectCodexUserIntegration">,
  ): Promise<CodexCloudConnectResult> {
    if (this.attemptId !== attemptId) {
      return Promise.reject(
        new Error("This ChatGPT login attempt is no longer active."),
      );
    }
    if (this.connection) return this.connection;
    this.connection = this.upload(attemptId, client).finally(() => {
      this.attemptId = null;
      this.connection = null;
    });
    return this.connection;
  }

  async cancel(attemptId: string): Promise<void> {
    await this.preparation?.catch(() => undefined);
    if (this.attemptId !== attemptId) return;
    // The upload can rotate tokens, so closing the view must not interrupt its cleanup.
    if (this.connection) {
      await this.connection.catch(() => undefined);
      return;
    }
    await this.host.cancel(attemptId);
    if (this.attemptId === attemptId) this.attemptId = null;
  }

  private async upload(
    attemptId: string,
    client: Pick<PostHogAPIClient, "connectCodexUserIntegration">,
  ): Promise<CodexCloudConnectResult> {
    let integration: UserCodexIntegration;
    try {
      const tokens = await this.host.read(attemptId);
      integration = await client.connectCodexUserIntegration(tokens);
    } catch (error) {
      await this.host.finish(attemptId);
      throw error;
    }
    let staleFileError: Error | null = null;
    try {
      await this.host.remove(attemptId);
    } catch (error) {
      staleFileError =
        error instanceof Error ? error : new Error(String(error));
    }
    try {
      await this.host.finish(attemptId);
    } catch (error) {
      staleFileError ??=
        error instanceof Error ? error : new Error(String(error));
    }
    return { integration, staleFileError };
  }
}

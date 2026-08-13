import { inject, injectable } from "inversify";
import { GITHUB_CONNECT_CLIENT, type GithubConnectClient } from "./identifiers";

@injectable()
export class GithubConnectService {
  private reconnectingInstallationId: string | null = null;
  private reportedFailureFingerprint: string | null = null;

  constructor(
    @inject(GITHUB_CONNECT_CLIENT)
    private readonly client: GithubConnectClient,
  ) {}

  shouldReportFailure(fingerprint: string | null): boolean {
    if (fingerprint === null) {
      this.reportedFailureFingerprint = null;
      return false;
    }
    if (this.reportedFailureFingerprint === fingerprint) return false;
    this.reportedFailureFingerprint = fingerprint;
    return true;
  }

  async disconnectInstallation(installationId: string): Promise<void> {
    await this.client.disconnectGithubUserIntegration(installationId);
  }

  isReconnecting(installationId: string): boolean {
    return this.reconnectingInstallationId === installationId;
  }

  isAnyReconnectInFlight(): boolean {
    return this.reconnectingInstallationId !== null;
  }

  async reconnectStaleInstallation(
    installationId: string,
    connect: () => Promise<void>,
  ): Promise<void> {
    if (this.reconnectingInstallationId !== null) return;
    this.reconnectingInstallationId = installationId;
    try {
      await this.client.disconnectGithubUserIntegration(installationId);
      await connect();
    } finally {
      this.reconnectingInstallationId = null;
    }
  }
}

import { chmodSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import type { OAuthAuthInfo, OAuthCredentials } from "@earendil-works/pi-ai";
import {
  loginPosthog,
  refreshPosthog,
} from "@posthog/harness/extensions/posthog-provider/oauth";
import { type CloudRegion, getCloudUrlFromRegion } from "@posthog/shared";

// Its own token chain, so a refresh here never rotates away hog's refresh token.
const AUTH_PATH = join(homedir(), ".config", "posthog-tui", "auth.json");

export interface SignInCallbacks {
  onAuth: (info: OAuthAuthInfo) => void;
  signal?: AbortSignal;
}

export class TuiAuth {
  private refreshing: Promise<string> | null = null;

  private constructor(
    private credentials: OAuthCredentials,
    private readonly path: string,
  ) {}

  static load(path: string = AUTH_PATH): TuiAuth | null {
    try {
      return new TuiAuth(JSON.parse(readFileSync(path, "utf8")), path);
    } catch {
      return null;
    }
  }

  static async login(
    region: CloudRegion,
    { onAuth, signal }: SignInCallbacks,
    path: string = AUTH_PATH,
  ): Promise<TuiAuth> {
    const credentials = await loginPosthog(
      {
        onAuth,
        signal,
        onDeviceCode: () => {},
        onPrompt: async () => "",
        onSelect: async () => region,
      },
      region,
    );
    save(credentials, path);
    return new TuiAuth(credentials, path);
  }

  get apiHost(): string {
    return getCloudUrlFromRegion(this.credentials.region as CloudRegion);
  }

  async getAccessToken(): Promise<string> {
    return this.credentials.expires > Date.now()
      ? this.credentials.access
      : this.refreshAccessToken();
  }

  refreshAccessToken(): Promise<string> {
    this.refreshing ??= refreshPosthog(
      this.credentials.region as CloudRegion,
      this.credentials,
    )
      .then((credentials) => {
        this.credentials = credentials;
        save(credentials, this.path);
        return credentials.access;
      })
      .finally(() => {
        this.refreshing = null;
      });
    return this.refreshing;
  }
}

function save(credentials: OAuthCredentials, path: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(credentials), { mode: 0o600 });
  chmodSync(path, 0o600);
}

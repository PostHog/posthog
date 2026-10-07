import {
  chmodSync,
  mkdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
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

// Today's briefing needs scopes the desktop app's shared set leaves out. Only this app asks for them.
const TUI_SCOPES = ["today:read", "today:write"];

export const REGIONS: { id: CloudRegion; label: string }[] = [
  { id: "us", label: "US cloud" },
  { id: "eu", label: "EU cloud" },
  { id: "dev", label: "Local dev" },
];

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
      TUI_SCOPES,
    );
    const user = await fetch(
      `${getCloudUrlFromRegion(region)}/api/users/@me/`,
      { headers: { Authorization: `Bearer ${credentials.access}` }, signal },
    );
    const account = user.ok
      ? ((await user.json()) as { uuid?: string }).uuid
      : undefined;
    save({ ...credentials, account }, path);
    return new TuiAuth({ ...credentials, account }, path);
  }

  static logout(path: string = AUTH_PATH): void {
    rmSync(path, { force: true });
  }

  get region(): CloudRegion {
    return this.credentials.region as CloudRegion;
  }

  // The signed-in user's id. A session saved before sign-in recorded it has none.
  get account(): string | undefined {
    return this.credentials.account as string | undefined;
  }

  get apiHost(): string {
    return getCloudUrlFromRegion(this.region);
  }

  async oauthCredentials(): Promise<{
    access: string;
    refresh: string;
    expires: number;
    region: CloudRegion;
  }> {
    const access = await this.getAccessToken();
    const { refresh, expires } = this.credentials;
    return { access, refresh, expires, region: this.region };
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
      .then((refreshed) => {
        const credentials = { ...refreshed, account: this.account };
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

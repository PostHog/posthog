export const OAUTH_SERVICE = Symbol.for("posthog.core.oauthService");
export const OAUTH_HOST = Symbol.for("posthog.core.oauthHost");

export interface OAuthCallbackReceiver {
  waitForCode(options: {
    port: number;
    timeoutMs: number;
    signal?: AbortSignal;
    onListening?: () => void;
  }): Promise<string>;
}

export interface OAuthEnv {
  readonly isDev: boolean;
}

export interface OAuthHost extends OAuthCallbackReceiver, OAuthEnv {}

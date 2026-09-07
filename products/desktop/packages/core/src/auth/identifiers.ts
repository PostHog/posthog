import type {
  AuthDeploymentTarget,
  CloudRegion,
  DesktopPreviewManifest,
} from "@posthog/shared";
import type {
  CancelFlowOutput,
  DeploymentTarget,
  RefreshTokenOutput,
  StartFlowOutput,
} from "./oauth.schemas";

export interface AuthSessionRecord {
  refreshTokenEncrypted: string;
  cloudRegion: CloudRegion;
  deploymentTarget: DeploymentTarget;
  /**
   * Deployment identity recorded at sign-in for a preview session; null for
   * ordinary regions. A changed value means the stored credentials belong to
   * a different deployment and must be discarded, not refreshed.
   */
  deploymentId: string | null;
  selectedProjectId: number | null;
  scopeVersion: number;
}

export interface PersistAuthSessionRecord {
  refreshTokenEncrypted: string;
  cloudRegion: CloudRegion;
  deploymentTarget: DeploymentTarget;
  deploymentId: string | null;
  selectedProjectId: number | null;
  scopeVersion: number;
}

export interface AuthPreferenceRecord {
  accountKey: string;
  cloudRegion: CloudRegion;
  lastSelectedProjectId: number | null;
  lastSelectedOrgId: string | null;
}

export interface AuthOrgProjectPreferenceRecord {
  accountKey: string;
  cloudRegion: CloudRegion;
  orgId: string;
  lastSelectedProjectId: number;
}

/**
 * Persists the encrypted auth session. Desktop adapter wraps the
 * workspace-server AuthSessionRepository (drizzle rows mapped to the domain
 * record above so core never imports workspace-server).
 */
export interface IAuthSessionStore {
  getCurrent(): AuthSessionRecord | null;
  saveCurrent(input: PersistAuthSessionRecord): void;
  clearCurrent(): void;
}

export const AUTH_SESSION_STORE = Symbol.for("posthog.core.auth.sessionStore");

/**
 * Persists per-account project preference. Desktop adapter wraps the
 * workspace-server AuthPreferenceRepository.
 */
export interface IAuthPreferenceStore {
  get(
    accountKey: string,
    cloudRegion: CloudRegion,
  ): AuthPreferenceRecord | null;
  save(input: AuthPreferenceRecord): void;
  getOrgProject(
    accountKey: string,
    cloudRegion: CloudRegion,
    orgId: string,
  ): AuthOrgProjectPreferenceRecord | null;
  saveOrgProject(input: AuthOrgProjectPreferenceRecord): void;
}

export const AUTH_PREFERENCE_STORE = Symbol.for(
  "posthog.core.auth.preferenceStore",
);

/**
 * Drives the host OAuth login/refresh flow. Desktop adapter wraps the
 * Electron-coupled OAuthService (loopback callback server, deep links,
 * browser launch, window focus).
 */
export interface IAuthOAuthFlowService {
  startFlow(target: AuthDeploymentTarget): Promise<StartFlowOutput>;
  startSignupFlow(target: AuthDeploymentTarget): Promise<StartFlowOutput>;
  refreshToken(
    refreshToken: string,
    target: AuthDeploymentTarget,
  ): Promise<RefreshTokenOutput>;
  cancelFlow(): CancelFlowOutput;
}

export const AUTH_OAUTH_FLOW_SERVICE = Symbol.for(
  "posthog.core.auth.oauthFlow",
);

/**
 * Machine-bound symmetric cipher for the refresh token at rest. Desktop adapter
 * wraps the existing encryption util (node:crypto + machine id); the web adapter
 * uses a non-extractable Web Crypto key (async), so the contract is async.
 */
export interface IAuthTokenCipher {
  encrypt(plaintext: string): Promise<string>;
  decrypt(encrypted: string): Promise<string | null>;
}

export const AUTH_TOKEN_CIPHER = Symbol.for("posthog.core.auth.tokenCipher");

export interface ConnectivityStatus {
  isOnline: boolean;
}

/**
 * Reports network connectivity so the session refresh can avoid pointless
 * offline attempts and recover when the network returns.
 */
export interface IAuthConnectivity {
  getStatus(): ConnectivityStatus;
  onStatusChange(handler: (status: ConnectivityStatus) => void): () => void;
}

export const AUTH_CONNECTIVITY = Symbol.for("posthog.core.auth.connectivity");

/**
 * Optional dev/test access-token override (host build env, e.g. Vite
 * VITE_POSTHOG_ACCESS_TOKEN_OVERRIDE). Injected as a value so core stays pure
 * (no process.env). Bind to null when unset.
 */
export const AUTH_TOKEN_OVERRIDE = Symbol.for(
  "posthog.core.auth.tokenOverride",
);

/**
 * The preview deployment this build targets, or null in an ordinary build.
 * A host binds the validated build-time manifest as a constant value; core
 * resolves every API origin, OAuth client id, and gateway URL through it, so
 * a preview build can never reach a production deployment and an ordinary
 * build is unaffected. Injected rather than imported so web and mobile hosts
 * that never offer preview selection bind null and stay unchanged.
 */
export const AUTH_PREVIEW_DEPLOYMENT = Symbol.for(
  "posthog.core.auth.previewDeployment",
);

export type AuthPreviewDeployment = DesktopPreviewManifest | null;

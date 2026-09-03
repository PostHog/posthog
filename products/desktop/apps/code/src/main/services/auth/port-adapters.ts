import type {
  AuthOrgProjectPreferenceRecord,
  AuthPreferenceRecord,
  AuthSessionRecord,
  IAuthOAuthFlowService,
  IAuthPreferenceStore,
  IAuthSessionStore,
  IAuthTokenCipher,
  PersistAuthSessionRecord,
} from "@posthog/core/auth/identifiers";
import type {
  CancelFlowOutput,
  RefreshTokenOutput,
  StartFlowOutput,
} from "@posthog/core/auth/oauth.schemas";
import { OAUTH_SERVICE } from "@posthog/core/oauth/identifiers";
import type { OAuthService } from "@posthog/core/oauth/oauth";
import type { CloudRegion } from "@posthog/shared";
import type { IAuthPreferenceRepository } from "@posthog/workspace-server/db/repositories/auth-preference-repository";
import type { IAuthSessionRepository } from "@posthog/workspace-server/db/repositories/auth-session-repository";
import { inject, injectable } from "inversify";
import {
  AUTH_PREFERENCE_REPOSITORY,
  AUTH_SESSION_REPOSITORY,
} from "../../di/tokens";
import { decrypt, encrypt } from "../../utils/encryption";

@injectable()
export class TokenCipherPortAdapter implements IAuthTokenCipher {
  encrypt(plaintext: string): Promise<string> {
    return Promise.resolve(encrypt(plaintext));
  }

  decrypt(encrypted: string): Promise<string | null> {
    return Promise.resolve(decrypt(encrypted));
  }
}

@injectable()
export class OAuthFlowPortAdapter implements IAuthOAuthFlowService {
  constructor(
    @inject(OAUTH_SERVICE)
    private readonly oauth: OAuthService,
  ) {}

  startFlow(region: CloudRegion): Promise<StartFlowOutput> {
    return this.oauth.startFlow(region);
  }

  startSignupFlow(region: CloudRegion): Promise<StartFlowOutput> {
    return this.oauth.startSignupFlow(region);
  }

  startOrganizationCreationFlow(region: CloudRegion): Promise<StartFlowOutput> {
    return this.oauth.startOrganizationCreationFlow(region);
  }

  refreshToken(
    refreshToken: string,
    region: CloudRegion,
  ): Promise<RefreshTokenOutput> {
    return this.oauth.refreshToken(refreshToken, region);
  }

  cancelFlow(): CancelFlowOutput {
    return this.oauth.cancelFlow();
  }
}

@injectable()
export class AuthSessionPortAdapter implements IAuthSessionStore {
  constructor(
    @inject(AUTH_SESSION_REPOSITORY)
    private readonly repository: IAuthSessionRepository,
  ) {}

  getCurrent(): AuthSessionRecord | null {
    const row = this.repository.getCurrent();
    if (!row) {
      return null;
    }
    return {
      refreshTokenEncrypted: row.refreshTokenEncrypted,
      cloudRegion: row.cloudRegion,
      selectedProjectId: row.selectedProjectId,
      scopeVersion: row.scopeVersion,
    };
  }

  saveCurrent(input: PersistAuthSessionRecord): void {
    this.repository.saveCurrent(input);
  }

  clearCurrent(): void {
    this.repository.clearCurrent();
  }
}

@injectable()
export class AuthPreferencePortAdapter implements IAuthPreferenceStore {
  constructor(
    @inject(AUTH_PREFERENCE_REPOSITORY)
    private readonly repository: IAuthPreferenceRepository,
  ) {}

  get(
    accountKey: string,
    cloudRegion: CloudRegion,
  ): AuthPreferenceRecord | null {
    const row = this.repository.get(accountKey, cloudRegion);
    if (!row) {
      return null;
    }
    return {
      accountKey: row.accountKey,
      cloudRegion: row.cloudRegion,
      lastSelectedProjectId: row.lastSelectedProjectId,
      lastSelectedOrgId: row.lastSelectedOrgId,
    };
  }

  save(input: AuthPreferenceRecord): void {
    this.repository.save(input);
  }

  getOrgProject(
    accountKey: string,
    cloudRegion: CloudRegion,
    orgId: string,
  ): AuthOrgProjectPreferenceRecord | null {
    const row = this.repository.getOrgProject(accountKey, cloudRegion, orgId);
    if (!row) {
      return null;
    }
    return {
      accountKey: row.accountKey,
      cloudRegion: row.cloudRegion,
      orgId: row.orgId,
      lastSelectedProjectId: row.lastSelectedProjectId,
    };
  }

  saveOrgProject(input: AuthOrgProjectPreferenceRecord): void {
    this.repository.saveOrgProject(input);
  }
}

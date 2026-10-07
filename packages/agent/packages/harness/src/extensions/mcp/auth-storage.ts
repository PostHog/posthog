/**
 * File-based OAuth credential storage for MCP servers.
 *
 * One JSON file per server under `<agentDir>/mcp-auth/` (dir 0700, files
 * 0600), keyed by a SHA-256 hash of the server name so arbitrary names are
 * filesystem-safe. Each entry records the server URL it was issued for;
 * credentials are treated as invalid when the configured URL changes.
 */

import { createHash } from "node:crypto";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";

/** OAuth tokens as persisted on disk. */
export interface StoredTokens {
  accessToken: string;
  refreshToken?: string;
  /** Unix timestamp in seconds. */
  expiresAt?: number;
  scope?: string;
}

/** OAuth client information from dynamic (or static) registration. */
export interface StoredClientInfo {
  clientId: string;
  clientSecret?: string;
  clientIdIssuedAt?: number;
  clientSecretExpiresAt?: number;
  redirectUris?: string[];
}

/** Complete auth entry for one server. */
export interface AuthEntry {
  /** URL these credentials were issued for. */
  serverUrl?: string;
  tokens?: StoredTokens;
  clientInfo?: StoredClientInfo;
  /** PKCE code verifier for the in-flight authorization. */
  codeVerifier?: string;
  /**
   * OAuth `state` parameter of the in-flight interactive flow. Its presence
   * marks a user-initiated flow; background reconnects must not start one.
   */
  oauthState?: string;
  /** Unix timestamp (ms) of the last token save, for status display. */
  savedAt?: number;
}

export interface AuthStatus {
  hasTokens: boolean;
  /** True when tokens exist and carry an expiry in the past. */
  expired: boolean;
  savedAt?: number;
}

export function defaultAuthStorageDir(): string {
  return join(getAgentDir(), "mcp-auth");
}

export class McpAuthStorage {
  private readonly baseDir: string;

  constructor(baseDir: string = defaultAuthStorageDir()) {
    this.baseDir = baseDir;
  }

  private fileFor(serverName: string): string {
    const key = createHash("sha256").update(serverName, "utf8").digest("hex");
    return join(this.baseDir, `${key}.json`);
  }

  /** Read the raw entry, regardless of which URL it was issued for. */
  async read(serverName: string): Promise<AuthEntry | undefined> {
    try {
      const text = await readFile(this.fileFor(serverName), "utf8");
      return JSON.parse(text) as AuthEntry;
    } catch {
      return undefined;
    }
  }

  /**
   * Read the entry only if it was issued for `serverUrl`. Entries for a
   * different (or unknown) URL are treated as absent.
   */
  async readForUrl(
    serverName: string,
    serverUrl: string,
  ): Promise<AuthEntry | undefined> {
    const entry = await this.read(serverName);
    if (!entry?.serverUrl || entry.serverUrl !== serverUrl) return undefined;
    return entry;
  }

  /**
   * Mutate the entry for a server. If the stored entry was issued for a
   * different URL it is discarded first, so stale credentials never leak
   * across server URLs.
   */
  async update(
    serverName: string,
    serverUrl: string,
    mutate: (entry: AuthEntry) => void,
  ): Promise<void> {
    const existing = await this.read(serverName);
    const entry: AuthEntry =
      existing?.serverUrl === serverUrl ? existing : { serverUrl };
    entry.serverUrl = serverUrl;
    mutate(entry);
    await mkdir(this.baseDir, { recursive: true, mode: 0o700 });
    await writeFile(this.fileFor(serverName), JSON.stringify(entry, null, 2), {
      mode: 0o600,
    });
  }

  /** Remove all credentials for a server. */
  async clear(serverName: string): Promise<void> {
    await rm(this.fileFor(serverName), { force: true });
  }

  /** Remove specific fields, keeping the rest of the entry. */
  async clearFields(
    serverName: string,
    fields: ReadonlyArray<keyof Omit<AuthEntry, "serverUrl">>,
  ): Promise<void> {
    const entry = await this.read(serverName);
    if (!entry?.serverUrl) return;
    await this.update(serverName, entry.serverUrl, (next) => {
      for (const field of fields) delete next[field];
    });
  }

  /**
   * Summarized status for display (`/mcp:auth` listing). When `serverUrl`
   * is given, credentials issued for a different URL count as absent —
   * matching how every other code path treats them.
   */
  async status(serverName: string, serverUrl?: string): Promise<AuthStatus> {
    const entry = serverUrl
      ? await this.readForUrl(serverName, serverUrl)
      : await this.read(serverName);
    const tokens = entry?.tokens;
    if (!tokens) return { hasTokens: false, expired: false };
    return {
      hasTokens: true,
      expired:
        tokens.expiresAt !== undefined && tokens.expiresAt < Date.now() / 1000,
      ...(entry.savedAt !== undefined ? { savedAt: entry.savedAt } : {}),
    };
  }
}

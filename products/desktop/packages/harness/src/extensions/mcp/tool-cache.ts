/**
 * Disk-backed cache of MCP server tool metadata (name + description).
 *
 * Lets the `mcp` proxy tool's search work for `lifecycle: "lazy"` servers
 * that are not currently connected — without spawning/dialing them just to
 * answer "what tools does this server have". The cache is written on every
 * successful `tools/list` refresh and invalidated (implicitly ignored) when
 * the server's config changes, via `configHash`.
 *
 * Single JSON file, read-modify-write. Best effort: this is a cache, not a
 * source of truth, so a lost write under concurrent access just means a
 * slightly stale search result — never correctness for the actual tool
 * call, which always goes through a live connection.
 */

import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { getAgentDir } from "@earendil-works/pi-coding-agent";
import type { McpServerConfig } from "./config";

export interface CachedToolInfo {
  /** pi tool name (`<prefix>_<server>_<tool>`). */
  name: string;
  /** Original MCP tool name. */
  mcpName: string;
  description: string;
}

export interface ToolCacheEntry {
  /** Hash of the config fields that affect what tools/schemas look like. */
  configHash: string;
  /** Server-level description from config, if set. */
  description?: string;
  tools: CachedToolInfo[];
  /** Unix timestamp (ms) this entry was written. */
  cachedAt: number;
}

type ToolCacheFile = Record<string, ToolCacheEntry>;

export function defaultToolCachePath(): string {
  return join(getAgentDir(), "mcp-cache.json");
}

/**
 * Hash of the config fields that determine a server's tool catalog.
 * Cache entries aren't actively purged on mismatch — callers compare this
 * against the current config's hash and ignore stale entries themselves.
 */
export function hashServerConfig(config: McpServerConfig): string {
  const relevant = {
    transport: config.transport,
    command: config.command,
    args: config.args,
    env: config.env,
    url: config.url,
    headers: config.headers,
  };
  return createHash("sha256")
    .update(JSON.stringify(relevant))
    .digest("hex")
    .slice(0, 16);
}

export class McpToolCache {
  private readonly path: string;

  constructor(path: string = defaultToolCachePath()) {
    this.path = path;
  }

  private async readAll(): Promise<ToolCacheFile> {
    try {
      return JSON.parse(await readFile(this.path, "utf8")) as ToolCacheFile;
    } catch {
      return {};
    }
  }

  private async writeAll(all: ToolCacheFile): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    await writeFile(this.path, JSON.stringify(all, null, 2));
  }

  /** Cached entry for a server, regardless of whether its config still matches. */
  async get(serverName: string): Promise<ToolCacheEntry | undefined> {
    return (await this.readAll())[serverName];
  }

  /** Cached entry only if it matches the server's current config. */
  async getIfCurrent(
    serverName: string,
    config: McpServerConfig,
  ): Promise<ToolCacheEntry | undefined> {
    const entry = await this.get(serverName);
    if (!entry || entry.configHash !== hashServerConfig(config))
      return undefined;
    return entry;
  }

  async set(
    serverName: string,
    entry: Omit<ToolCacheEntry, "cachedAt">,
  ): Promise<void> {
    const all = await this.readAll();
    all[serverName] = { ...entry, cachedAt: Date.now() };
    await this.writeAll(all);
  }

  async clear(serverName: string): Promise<void> {
    const all = await this.readAll();
    delete all[serverName];
    await this.writeAll(all);
  }

  async all(): Promise<ToolCacheFile> {
    return this.readAll();
  }
}

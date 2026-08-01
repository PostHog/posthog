/**
 * Configuration loading, validation, and merging for the MCP extension.
 *
 * Config file locations (highest priority first):
 *   1. `<cwd>/<CONFIG_DIR_NAME>/mcp.json` — project-level config
 *   2. `<agentDir>/mcp.json`              — global config (`~/.pi/agent/mcp.json`)
 *
 * Project servers/settings override global servers/settings per key
 * (shallow merge). No env-var interpolation — WYSIWYG config.
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { CONFIG_DIR_NAME, getAgentDir } from "@earendil-works/pi-coding-agent";
import { z } from "zod";
import { McpError } from "./errors";

const authConfigSchema = z.object({
  /** Auth type. Only "oauth" (authorization_code + PKCE) is supported. */
  type: z.literal("oauth").default("oauth"),
  /** Optional scope to request during authorization. */
  scope: z.string().optional(),
  /** Pre-registered client_id (skips dynamic client registration). */
  clientId: z.string().optional(),
  /** Pre-registered client_secret. */
  clientSecret: z.string().optional(),
  /**
   * Fixed OAuth redirect URL (must be an http:// loopback URL with an
   * explicit port, e.g. "http://127.0.0.1:19876/callback"). Required when
   * the client was pre-registered with an exact redirect URI; otherwise the
   * callback server picks an ephemeral port.
   */
  redirectUrl: z.url().optional(),
  /** client_name sent during dynamic registration. */
  clientName: z.string().optional(),
});

const serverConfigSchema = z
  .object({
    /** Executable to spawn (e.g. "npx", "node", "uvx"). Required for stdio. */
    command: z.string().optional(),
    /** Arguments passed to the command. */
    args: z.array(z.string()).default([]),
    /**
     * Extra environment variables passed to the child process as literals.
     * Merged over `process.env`.
     */
    env: z.record(z.string(), z.string()).optional(),
    /** Transport protocol. Default: "stdio". */
    transport: z.enum(["stdio", "streamable-http", "sse"]).default("stdio"),
    /** URL for streamable-http or sse transports. */
    url: z.url().optional(),
    /**
     * Static HTTP headers sent with every request (streamable-http/sse only).
     * Useful for API-key auth, e.g. `{ "Authorization": "Bearer <key>" }`.
     */
    headers: z.record(z.string(), z.string()).optional(),
    /**
     * OAuth2 configuration (streamable-http/sse only). When set, connections
     * attach/refresh tokens automatically and `/mcp:auth <server>` runs the
     * interactive browser flow (discovery, dynamic client registration,
     * PKCE, token exchange).
     */
    auth: authConfigSchema.optional(),
    /**
     * "eager" — start at session_start.
     * "lazy"  — start on first use of one of its tools (via the `mcp`
     *           proxy tool) or manually via /mcp:start (default).
     */
    lifecycle: z.enum(["eager", "lazy"]).default("lazy"),
    /** Per-request timeout in ms. Overrides the global setting. */
    requestTimeoutMs: z.number().positive().optional(),
    /** Opt-in heartbeat (ping) interval in ms. Default: disabled. */
    healthCheckIntervalMs: z.number().positive().optional(),
    /**
     * Auto-disconnect a `lifecycle: "lazy"` server this many ms after its
     * last tool call (metadata stays cached so search keeps working; the
     * next call reconnects transparently). Ignored for eager servers.
     */
    idleTimeoutMs: z.number().positive().optional(),
    /**
     * One-line summary shown by the `mcp` proxy tool's search results
     * before the server has ever connected (its real tool list isn't known
     * yet). Ignored once tools are cached/discovered.
     */
    description: z.string().optional(),
    /**
     * Which of this server's tools are registered directly as first-class
     * pi tools (always in the model's context) versus left searchable only
     * through the `mcp` proxy tool (`mcp({ search / tool })`), which keeps
     * their schemas out of context until requested.
     *   `true`      — all tools direct.
     *   `false`     — no tools direct; all proxy-only (default).
     *   `string[]`  — only the named (MCP-side) tool names are direct.
     */
    directTools: z.union([z.boolean(), z.array(z.string())]).default(false),
  })
  .superRefine((cfg, ctx) => {
    if (cfg.transport === "stdio" && cfg.command === undefined) {
      ctx.addIssue({
        code: "custom",
        message: `"command" is required for stdio transport`,
      });
    }
    if (cfg.transport !== "stdio" && cfg.url === undefined) {
      ctx.addIssue({
        code: "custom",
        message: `"url" is required for ${cfg.transport} transport`,
      });
    }
    if (cfg.transport === "stdio" && cfg.auth !== undefined) {
      ctx.addIssue({
        code: "custom",
        message: `"auth" is only supported for streamable-http and sse transports`,
      });
    }
  });

const settingsSchema = z.object({
  /**
   * Prefix used in pi tool names: `<prefix>_<server>_<tool>`.
   * Must match [a-zA-Z0-9_]. Default: "mcp".
   */
  toolPrefix: z
    .string()
    .regex(/^[a-zA-Z0-9_]+$/, "toolPrefix must match [a-zA-Z0-9_]")
    .default("mcp"),
  /** Default per-request timeout in ms for all servers. Default: 30000. */
  requestTimeoutMs: z.number().positive().default(30_000),
  /** Maximum retry attempts when a server fails to connect. Default: 3. */
  maxRetries: z.number().int().min(0).max(10).default(3),
  /** Max results returned by the `mcp` proxy tool's search. Default: 15. */
  searchResultLimit: z.number().int().positive().default(15),
});

const mcpConfigSchema = z.object({
  settings: settingsSchema.prefault({}),
  mcpServers: z.record(z.string(), serverConfigSchema).default({}),
});

export type McpAuthConfig = z.output<typeof authConfigSchema>;
export type McpServerConfig = z.output<typeof serverConfigSchema>;
export type McpSettings = z.output<typeof settingsSchema>;
export type McpConfig = z.output<typeof mcpConfigSchema>;

export function emptyConfig(): McpConfig {
  return mcpConfigSchema.parse({});
}

async function readJsonFile(path: string): Promise<unknown | null> {
  let text: string;
  try {
    text = await readFile(path, "utf8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new McpError(
      `Failed to read ${path}: ${err instanceof Error ? err.message : String(err)}`,
      "<config>",
      "config",
      err,
    );
  }
  try {
    return JSON.parse(text) as unknown;
  } catch (err) {
    throw new McpError(
      `Invalid JSON in ${path}: ${err instanceof Error ? err.message : String(err)}`,
      "<config>",
      "config",
      err,
    );
  }
}

export function parseConfig(raw: unknown, sourcePath: string): McpConfig {
  const result = mcpConfigSchema.safeParse(raw);
  if (!result.success) {
    const issues = result.error.issues
      .map((issue) => `  ${issue.path.join(".")}: ${issue.message}`)
      .join("\n");
    throw new McpError(
      `Invalid mcp.json at ${sourcePath}:\n${issues}`,
      "<config>",
      "config",
    );
  }
  return result.data;
}

/**
 * Merge raw (pre-validation) configs so that only keys the project file
 * actually sets override the global file — merging parsed configs would let
 * project-side schema defaults clobber explicit global settings.
 */
export function mergeRawConfigs(
  globalRaw: unknown,
  projectRaw: unknown,
): unknown {
  const g = (globalRaw ?? {}) as Record<string, unknown>;
  const p = (projectRaw ?? {}) as Record<string, unknown>;
  return {
    // Shallow spread: project settings override global settings per key.
    settings: {
      ...((g.settings as Record<string, unknown>) ?? {}),
      ...((p.settings as Record<string, unknown>) ?? {}),
    },
    // Per-server override: a project server entry completely replaces a
    // global entry with the same name.
    mcpServers: {
      ...((g.mcpServers as Record<string, unknown>) ?? {}),
      ...((p.mcpServers as Record<string, unknown>) ?? {}),
    },
  };
}

export interface LoadConfigOptions {
  /** Override the global config path (tests). Default: `<agentDir>/mcp.json`. */
  globalPath?: string;
  /**
   * Override the project config path (tests).
   * Default: `<cwd>/<CONFIG_DIR_NAME>/mcp.json`.
   */
  projectPath?: string;
  /**
   * Whether to honor the project-level config. Callers should pass
   * `ctx.isProjectTrusted()` so untrusted projects cannot inject servers.
   * Default: true.
   */
  includeProject?: boolean;
}

export type ConfigLoader = (
  cwd: string,
  options?: LoadConfigOptions,
) => Promise<McpConfig>;

/**
 * Load and merge global and project configs. Project config takes
 * precedence. Returns a fully validated, merged config.
 */
export const loadConfig: ConfigLoader = async (cwd, options = {}) => {
  const globalPath = options.globalPath ?? join(getAgentDir(), "mcp.json");
  const projectPath =
    options.projectPath ?? join(cwd, CONFIG_DIR_NAME, "mcp.json");
  const includeProject = options.includeProject ?? true;

  const [globalRaw, projectRaw] = await Promise.all([
    readJsonFile(globalPath),
    includeProject ? readJsonFile(projectPath) : Promise.resolve(null),
  ]);

  // Validate each file individually first so errors name the right file.
  const globalCfg =
    globalRaw !== null ? parseConfig(globalRaw, globalPath) : emptyConfig();
  if (projectRaw === null) return globalCfg;
  parseConfig(projectRaw, projectPath);

  return parseConfig(
    mergeRawConfigs(globalRaw, projectRaw),
    `${globalPath} + ${projectPath}`,
  );
};

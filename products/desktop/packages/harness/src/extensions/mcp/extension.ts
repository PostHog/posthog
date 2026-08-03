/**
 * MCP client extension for pi (replaces the community `pi-mcp-adapter`).
 *
 * Connects pi to MCP servers configured in `mcp.json` (global agent dir
 * and/or project `.pi/`), registers their tools as pi tools, and manages
 * server lifecycle across sessions.
 *
 * Commands:
 *   /mcp                     — status summary for all servers
 *   /mcp <name>              — detailed status + recent logs for one server
 *   /mcp:start <name>        — start a server (lazy servers, or after failure)
 *   /mcp:stop <name>         — stop a server and deactivate its tools
 *   /mcp:auth [name] [reset] — OAuth status / interactive browser flow
 *
 * Wiring: config → ServerManager → ToolBridge → pi API, with OAuth
 * credentials in McpAuthStorage and browser flows via auth-flow.ts.
 */

import { fileURLToPath } from "node:url";
import type {
  ExtensionAPI,
  ExtensionCommandContext,
  ExtensionContext,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import type { AutocompleteItem } from "@earendil-works/pi-tui";
import { Type } from "typebox";
import type { OAuthFlowRunner } from "./auth-flow";
import { runOAuthFlow } from "./auth-flow";
import { McpAuthStorage } from "./auth-storage";
import { CallbackServer } from "./callback-server";
import type { ConfigLoader, McpConfig } from "./config";
import { emptyConfig, loadConfig } from "./config";
import { describeError } from "./errors";
import { createMcpProxyTool } from "./proxy-tool";
import type { TransportFactory } from "./server-manager";
import { ServerManager } from "./server-manager";
import { ToolBridge } from "./tool-bridge";
import { McpToolCache } from "./tool-cache";

export interface McpExtensionOptions {
  /** Override config loading (tests). Default: read mcp.json files. */
  configLoader?: ConfigLoader;
  /** Override transport creation (tests). Default: stdio/http/sse via SDK. */
  transportFactory?: TransportFactory;
  /** Override OAuth credential storage (tests). */
  authStorage?: McpAuthStorage;
  /** Override the on-disk tool metadata cache (tests). */
  toolCache?: McpToolCache;
  /** Override the interactive OAuth flow (tests). */
  oauthFlow?: OAuthFlowRunner;
}

/** Open a URL in the user's default browser (best effort). Exported for tests. */
export async function openBrowser(
  pi: ExtensionAPI,
  url: string,
): Promise<void> {
  const [command, args] =
    process.platform === "darwin"
      ? ["open", [url]]
      : process.platform === "win32"
        ? // Not `cmd /c start`: cmd.exe would interpret the `&`s in the
          // authorization URL as command separators (truncating the URL and
          // executing attacker-influenceable remainders).
          ["rundll32", ["url.dll,FileProtocolHandler", url]]
        : ["xdg-open", [url]];
  const result = await pi.exec(command, args as string[]);
  if (result.code !== 0) {
    throw new Error(`Failed to open browser: exit code ${result.code}`);
  }
}

/**
 * Structural equality for parsed config objects. Zod's output preserves the
 * source JSON's key order, so a `JSON.stringify` comparison would treat a
 * config file whose fields were merely reordered (no value changes) as a
 * change and trigger a needless full teardown/rebuild on session resume.
 */
function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== "object" || typeof b !== "object" || !a || !b) {
    return false;
  }
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) {
      return false;
    }
    return a.every((value, i) => deepEqual(value, b[i]));
  }
  const aKeys = Object.keys(a as Record<string, unknown>);
  const bKeys = Object.keys(b as Record<string, unknown>);
  if (aKeys.length !== bKeys.length) return false;
  return aKeys.every((key) =>
    deepEqual(
      (a as Record<string, unknown>)[key],
      (b as Record<string, unknown>)[key],
    ),
  );
}

function isAuthRequiredError(message: string): boolean {
  return /unauthorized|401|invalid_token|authentication required/i.test(
    message,
  );
}

/**
 * Suffix a "run /mcp:auth <name>" hint onto an auth-required error — unless
 * the message already carries one (our own UnauthorizedError messages do).
 */
function authHint(serverName: string, message: string): string {
  return isAuthRequiredError(message) && !message.includes("/mcp:auth")
    ? ` — run /mcp:auth ${serverName}`
    : "";
}

export function createMcpExtension(
  options: McpExtensionOptions = {},
): ExtensionFactory {
  const configLoader = options.configLoader ?? loadConfig;
  const oauthFlow = options.oauthFlow ?? runOAuthFlow;

  return (pi: ExtensionAPI) => {
    // Session-scoped runtime. Created on session_start (per the extension
    // guidelines, factories must not start background resources) and torn
    // down on session_shutdown.
    let config: McpConfig = emptyConfig();
    let manager: ServerManager | null = null;
    let bridge: ToolBridge | null = null;
    // Constructed lazily so the factory does no filesystem work.
    let authStorage: McpAuthStorage | null = options.authStorage ?? null;
    let toolCache: McpToolCache | null = options.toolCache ?? null;
    // Updated on every session_start; read by the `mcp` proxy tool so it can
    // start a lazy server on demand with the right workspace root.
    let currentCwd = process.cwd();
    const callbackServer = new CallbackServer();
    /** Servers with an interactive OAuth flow currently in progress. */
    const authFlowsInFlight = new Set<string>();

    function getAuthStorage(): McpAuthStorage {
      authStorage ??= new McpAuthStorage();
      return authStorage;
    }

    function getToolCache(): McpToolCache {
      toolCache ??= new McpToolCache();
      return toolCache;
    }

    function buildRuntime(nextConfig: McpConfig): void {
      config = nextConfig;
      manager = new ServerManager(nextConfig, {
        authStorage: getAuthStorage(),
        ...(options.transportFactory
          ? { transportFactory: options.transportFactory }
          : {}),
      });
      const activeManager = manager;
      bridge = new ToolBridge(nextConfig.settings, pi, {
        toolCache: getToolCache(),
        onToolUsed: (serverName) => activeManager.touch(serverName),
      });
      const activeBridge = bridge;
      manager.setToolRefreshCallback(async (serverName, client) => {
        await activeBridge.refreshTools(
          serverName,
          client,
          activeManager.getRequestTimeoutMs(serverName),
          activeManager.getServer(serverName)?.config,
        );
        // A refresh that was in flight when the server was stopped would
        // otherwise re-activate tools whose execute closures hold a closed
        // client; the state flip in shutdown() is synchronous, so this check
        // reliably observes a concurrent stop.
        if (activeManager.getServer(serverName)?.state !== "ready") {
          activeBridge.deactivateServer(serverName);
        }
      });
      // Crashed/dropped connections deactivate the server's tools while the
      // background reconnect runs (a successful reconnect re-activates them
      // through the refresh callback above).
      manager.setDisconnectCallback((serverName) => {
        activeBridge.deactivateServer(serverName);
      });
    }

    async function teardown(): Promise<void> {
      if (manager && bridge) {
        for (const server of manager.getAllServers()) {
          bridge.deactivateServer(server.name);
        }
        await manager.shutdownAll();
      }
    }

    async function startEagerServers(ctx: ExtensionContext): Promise<void> {
      if (!manager) return;
      const activeManager = manager;
      const eager = activeManager
        .getAllServers()
        .filter((server) => server.config.lifecycle === "eager");
      await Promise.allSettled(
        eager.map(async (server) => {
          await activeManager.startServer(server.name, ctx.cwd);
          const state = activeManager.getServer(server.name);
          if (state && state.state !== "ready" && ctx.hasUI) {
            const message = state.lastError?.message ?? "";
            const hint = state.config.auth
              ? authHint(server.name, message)
              : "";
            ctx.ui.notify(
              `mcp: failed to start ${server.name}${message ? ` — ${message}` : ""}${hint}`,
              "error",
            );
          }
        }),
      );
    }

    // Contribute the bundled `mcp-servers` skill so the model knows how to
    // install/configure MCP servers on request (config schema, file
    // locations, OAuth, troubleshooting) without bloating the system prompt.
    pi.on("resources_discover", () => ({
      skillPaths: [fileURLToPath(new URL("./skills", import.meta.url))],
    }));

    pi.on("session_start", async (_event, ctx) => {
      let nextConfig: McpConfig;
      try {
        nextConfig = await configLoader(ctx.cwd, {
          includeProject: ctx.isProjectTrusted(),
        });
      } catch (err) {
        if (ctx.hasUI) {
          ctx.ui.notify(`mcp: config error — ${describeError(err)}`, "error");
        }
        return;
      }

      currentCwd = ctx.cwd;

      if (manager === null) {
        if (Object.keys(nextConfig.mcpServers).length === 0) return;
        buildRuntime(nextConfig);
      } else if (!deepEqual(nextConfig, config)) {
        // Config changed (e.g. resumed into a different project): tear down
        // the old runtime and rebuild from the new config.
        await teardown();
        buildRuntime(nextConfig);
      }

      await startEagerServers(ctx);
    });

    pi.on("session_shutdown", async () => {
      await callbackServer.stop();
      await teardown();
    });

    const completeServerNames = (prefix: string): AutocompleteItem[] | null => {
      if (!manager) return null;
      const items = manager
        .getAllServers()
        .map((server) => ({
          value: server.name,
          label: server.name,
          description: server.state,
        }))
        .filter((item) => item.value.startsWith(prefix));
      return items.length > 0 ? items : null;
    };

    pi.registerCommand("mcp", {
      description: "Show MCP server status. Usage: /mcp [server-name]",
      getArgumentCompletions: completeServerNames,
      handler: async (args: string, ctx: ExtensionCommandContext) => {
        if (!manager) {
          ctx.ui.notify(
            "mcp: no servers configured (create mcp.json in your agent dir or project .pi/)",
            "info",
          );
          return;
        }
        const serverName = args.trim();
        if (!serverName) {
          ctx.ui.notify(manager.getStatusSummary(), "info");
          return;
        }
        const server = manager.getServer(serverName);
        if (!server) {
          ctx.ui.notify(`mcp: no server named "${serverName}"`, "error");
          return;
        }
        const toolNames = bridge?.getToolNames(serverName) ?? [];
        const collisions = bridge?.getCollisions(serverName) ?? [];
        const detail = [
          `Server: ${serverName}`,
          `State:  ${server.state}`,
          `Retries: ${server.retryCount}`,
          server.lastError ? `Last error: ${server.lastError.message}` : null,
          toolNames.length > 0 ? `Tools: ${toolNames.join(", ")}` : null,
          collisions.length > 0
            ? `Tool name collisions: ${collisions
                .map((c) => `${c.mcpToolName} → ${c.piToolName}`)
                .join(", ")} (later definitions win)`
            : null,
          "",
          "Recent output:",
          manager.getServerLogs(serverName),
        ]
          .filter((line) => line !== null)
          .join("\n");
        ctx.ui.notify(detail, "info");
      },
    });

    pi.registerCommand("mcp:start", {
      description: "Start an MCP server. Usage: /mcp:start <server-name>",
      getArgumentCompletions: completeServerNames,
      handler: async (args: string, ctx: ExtensionCommandContext) => {
        const serverName = args.trim();
        if (!serverName) {
          ctx.ui.notify("Usage: /mcp:start <server-name>", "error");
          return;
        }
        if (!manager?.getServer(serverName)) {
          ctx.ui.notify(`mcp: no server named "${serverName}"`, "error");
          return;
        }
        try {
          await manager.startServer(serverName, ctx.cwd);
          const server = manager.getServer(serverName);
          if (server?.state === "ready") {
            ctx.ui.notify(`mcp: started ${serverName}`, "info");
          } else {
            const message = server?.lastError?.message ?? "";
            const hint = server?.config.auth
              ? authHint(serverName, message)
              : "";
            ctx.ui.notify(
              `mcp: failed to start ${serverName}${message ? ` — ${message}` : ""}${hint}`,
              "error",
            );
          }
        } catch (err) {
          ctx.ui.notify(
            `mcp: failed to start ${serverName} — ${describeError(err)}`,
            "error",
          );
        }
      },
    });

    pi.registerCommand("mcp:stop", {
      description: "Stop an MCP server. Usage: /mcp:stop <server-name>",
      getArgumentCompletions: completeServerNames,
      handler: async (args: string, ctx: ExtensionCommandContext) => {
        const serverName = args.trim();
        if (!serverName) {
          ctx.ui.notify("Usage: /mcp:stop <server-name>", "error");
          return;
        }
        if (!manager?.getServer(serverName)) {
          ctx.ui.notify(`mcp: no server named "${serverName}"`, "error");
          return;
        }
        bridge?.deactivateServer(serverName);
        await manager.stopServer(serverName);
        ctx.ui.notify(`mcp: stopped ${serverName}`, "info");
      },
    });

    const completeOauthServerNames = (
      prefix: string,
    ): AutocompleteItem[] | null => {
      if (!manager) return null;
      const items = manager
        .getAllServers()
        .filter((server) => server.config.auth)
        .map((server) => ({ value: server.name, label: server.name }))
        .filter((item) => item.value.startsWith(prefix));
      return items.length > 0 ? items : null;
    };

    // Search + call MCP tools without every server's schema catalog sitting
    // in context, and without every lazy server needing to be connected up
    // front (see ToolBridge's `directTools` gating and ServerManager's
    // on-demand start). Registered unconditionally like `mcp_auth` below —
    // config may not have loaded (or may add servers) yet.
    pi.registerTool(
      createMcpProxyTool({
        getManager: () => manager,
        getBridge: () => bridge,
        getToolCache: () => getToolCache(),
        getSettings: () => (manager ? config.settings : null),
        getCwd: () => currentCwd,
        authHint,
      }),
    );

    // Commands can't be invoked by the model. This tool lets the agent
    // start the browser OAuth flow when the user asks ("log in to X for
    // me") by queuing /mcp:auth as a follow-up user message.
    pi.registerTool({
      name: "mcp_auth",
      label: "MCP Auth",
      description:
        "Start the interactive browser OAuth login flow for a configured MCP server (queues /mcp:auth <server>). Use when the user asks to log in to / authenticate / authorize an MCP server.",
      parameters: Type.Object({
        server: Type.String({
          description: "MCP server name as configured in mcp.json",
        }),
      }),
      async execute(_toolCallId, params) {
        const serverName = params.server.trim();
        const server = manager?.getServer(serverName);
        if (!server) {
          throw new Error(`No MCP server named "${serverName}"`);
        }
        if (!server.config.auth) {
          throw new Error(
            `MCP server "${serverName}" has no OAuth config — add \`"auth": { "type": "oauth" }\` to it in mcp.json first.`,
          );
        }
        pi.sendUserMessage(`/mcp:auth ${serverName}`, {
          deliverAs: "followUp",
        });
        return {
          content: [
            {
              type: "text",
              text: `Queued /mcp:auth ${serverName} — the browser OAuth flow will start as soon as this turn finishes. Tell the user to complete the login in their browser.`,
            },
          ],
          details: {},
        };
      },
    });

    pi.registerCommand("mcp:auth", {
      description:
        "Authenticate an MCP server via OAuth. Usage: /mcp:auth [server-name] [reset]",
      getArgumentCompletions: completeOauthServerNames,
      handler: async (args: string, ctx: ExtensionCommandContext) => {
        const [serverName, flag] = args.trim().split(/\s+/).filter(Boolean);

        if (!serverName) {
          // List OAuth-enabled servers with their auth status.
          const authServers =
            manager?.getAllServers().filter((server) => server.config.auth) ??
            [];
          if (authServers.length === 0) {
            ctx.ui.notify(
              'mcp: no servers with OAuth configured. Add `"auth": { "type": "oauth" }` to a server in mcp.json.',
              "info",
            );
            return;
          }
          const storage = getAuthStorage();
          const lines = await Promise.all(
            authServers.map(async (server) => {
              const status = await storage.status(
                server.name,
                server.config.url,
              );
              const label = status.hasTokens
                ? status.expired
                  ? "tokens expired (refresh on next connect)"
                  : "authenticated"
                : "not authenticated";
              const since = status.savedAt
                ? ` since ${new Date(status.savedAt).toISOString()}`
                : "";
              return `  ${server.name}: ${label}${since}`;
            }),
          );
          ctx.ui.notify(
            ["Usage: /mcp:auth <server-name> [reset]", "", ...lines].join("\n"),
            "info",
          );
          return;
        }

        const server = manager?.getServer(serverName);
        if (!manager || !server) {
          ctx.ui.notify(`mcp: no server named "${serverName}"`, "error");
          return;
        }
        if (!server.config.auth || !server.config.url) {
          ctx.ui.notify(
            `mcp: server "${serverName}" has no OAuth config. Add \`"auth": { "type": "oauth" }\` (and a URL) to it in mcp.json.`,
            "error",
          );
          return;
        }

        // A second flow for the same server would overwrite the first's
        // oauthState/PKCE verifier in storage, and the first flow's cleanup
        // would then wipe the second's — corrupting both.
        if (authFlowsInFlight.has(serverName)) {
          ctx.ui.notify(
            `mcp: an OAuth flow for ${serverName} is already in progress — complete or wait for it first`,
            "error",
          );
          return;
        }
        authFlowsInFlight.add(serverName);

        const storage = getAuthStorage();
        try {
          // Stop the server so the new credentials apply on reconnect.
          // Unconditional: a "stopped" server can still hold a pending
          // background retry timer that would otherwise fire mid-flow.
          bridge?.deactivateServer(serverName);
          await manager.stopServer(serverName);

          if (flag === "reset") {
            await storage.clear(serverName);
            ctx.ui.notify(`mcp: cleared credentials for ${serverName}`, "info");
          }

          const result = await oauthFlow({
            serverName,
            serverUrl: server.config.url,
            auth: server.config.auth,
            storage,
            callbackServer,
            openUrl: (url) => openBrowser(pi, url),
            onAuthorizationUrl: (url) => {
              ctx.ui.notify(
                `mcp: complete authorization for ${serverName} in your browser:\n${url}`,
                "info",
              );
            },
          });

          ctx.ui.notify(
            result === "authorized"
              ? `mcp: ${serverName} already had valid credentials`
              : `mcp: ${serverName} authenticated successfully`,
            "info",
          );

          await manager.startServer(serverName, ctx.cwd);
          const state = manager.getServer(serverName);
          if (state?.state === "ready") {
            ctx.ui.notify(`mcp: started ${serverName}`, "info");
          } else if (state?.lastError) {
            ctx.ui.notify(
              `mcp: failed to start ${serverName} — ${state.lastError.message}`,
              "error",
            );
          }
        } catch (err) {
          ctx.ui.notify(
            `mcp: authentication failed for ${serverName} — ${describeError(err)}`,
            "error",
          );
        } finally {
          authFlowsInFlight.delete(serverName);
        }
      },
    });
  };
}

export default function mcp(pi: ExtensionAPI): void | Promise<void> {
  return createMcpExtension()(pi);
}

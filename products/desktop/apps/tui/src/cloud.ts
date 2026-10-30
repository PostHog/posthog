import { execFileSync } from "node:child_process";
import { appendFileSync, mkdirSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { machineClaudeAuth } from "@posthog/agent/adapters/claude/machine-auth";
import { hasClaudeLogin } from "@posthog/agent/adapters/claude/subscription-login";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { AuthService } from "@posthog/core/auth/auth";
import { createCloudTaskEngine } from "@posthog/core/cloud-task/cloud-task-engine";
import { GatewayTokenService } from "@posthog/core/llm-gateway/gateway-token";
import { CloudArtifactService } from "@posthog/core/sessions/cloudArtifactService";
import type { RootLogger, ScopedLogger } from "@posthog/di/logger";
import type { IAnalytics } from "@posthog/platform/analytics";
import type { IWorkspaceSettings } from "@posthog/platform/workspace-settings";
import { TRANSCRIPT_TAIL_WINDOW } from "@posthog/shared";
import type { IWorkspaceRepository } from "@posthog/workspace-server/db/repositories/workspace-repository";
import { AgentService } from "@posthog/workspace-server/services/agent/agent";
import { AgentAuthAdapter } from "@posthog/workspace-server/services/agent/auth-adapter";
import type {
  AgentAuth,
  AgentMcpApps,
} from "@posthog/workspace-server/services/agent/ports";
import { AuthProxyService } from "@posthog/workspace-server/services/auth-proxy/auth-proxy";
import { McpProxyService } from "@posthog/workspace-server/services/mcp-proxy/mcp-proxy";
import { LocalPiRpcClientFactory } from "@posthog/workspace-server/services/pi-session/pi-rpc-client-factory";
import type { PosthogPluginService } from "@posthog/workspace-server/services/posthog-plugin/posthog-plugin";
import { ProcessTrackingService } from "@posthog/workspace-server/services/process-tracking/process-tracking";
import type { TuiAuth } from "./auth";
import { type LocalStart, localStartFor } from "./billing";
import { chatgptAccount } from "./chatgpt";
import { currentRepository, PiChats } from "./chats";
import { ClaudeLocalSession } from "./claudeLocal";
import { claudeTokenStore } from "./claudeToken";
import { LOG_PATH } from "./errors";
import { type LocalAgent, LocalSession } from "./local";
import { LocalChats } from "./localChats";
import { type PiCommand, type PiControl, piControl } from "./models";
import { loadPrefs } from "./prefs";
import { CloudRuns } from "./runs";
import { TodayClient } from "./today";

interface TokenSource {
  getAccessToken(): Promise<string>;
  refreshAccessToken(): Promise<string>;
}

export function authenticatedFetch(
  auth: TokenSource,
  fetch: (
    input: string | Request,
    init?: RequestInit,
  ) => Promise<Response> = globalThis.fetch,
): (input: string | Request, init?: RequestInit) => Promise<Response> {
  const send = (
    input: string | Request,
    init: RequestInit | undefined,
    token: string,
  ) => {
    const headers = new Headers(init?.headers);
    headers.set("Authorization", `Bearer ${token}`);
    return fetch(input, { ...init, headers });
  };
  return async (input, init) => {
    const response = await send(input, init, await auth.getAccessToken());
    if (response.status !== 401) return response;
    return send(input, init, await auth.refreshAccessToken());
  };
}

// Ink owns the screen, so logs go to a file.
function fileLogger(scope: string): ScopedLogger {
  const write =
    (level: string) =>
    (...args: unknown[]): void =>
      appendFileSync(
        LOG_PATH,
        `${new Date().toISOString()} ${level} [${scope}] ${args
          .map((arg) => (typeof arg === "string" ? arg : JSON.stringify(arg)))
          .join(" ")}\n`,
      );
  return {
    debug: write("debug"),
    info: write("info"),
    warn: write("warn"),
    error: write("error"),
  };
}

const logger: RootLogger = { ...fileLogger("tui"), scope: fileLogger };

const noAnalytics: IAnalytics = {
  initialize: () => {},
  track: () => {},
  identify: () => {},
  setCurrentUserId: () => {},
  getCurrentUserId: () => null,
  getOrCreateSessionId: () => "posthog-tui",
  resetUser: () => {},
  captureException: () => {},
  flush: async () => {},
  shutdown: async () => {},
};

// MCP apps render inside the desktop app; the terminal has nowhere to show them.
// The user's own Claude Code, the one `claude auth login` signed in.
function claudeBinary(): string {
  try {
    return execFileSync("which", ["claude"], { encoding: "utf8" }).trim();
  } catch {
    return join(homedir(), ".local", "bin", "claude");
  }
}

// The desktop app's agent service, with its Electron-only needs stubbed: it only runs Claude Code here.
function createClaudeAgent(
  mcp: AgentAuthAdapter,
  logger: RootLogger,
): AgentService {
  const dataDir = join(homedir(), ".config", "posthog-tui", "agent");
  mkdirSync(join(dataDir, "plugin", "skills"), { recursive: true });
  const claude = claudeBinary();
  return new AgentService(
    new ProcessTrackingService(),
    { acquire: () => {}, release: () => {} },
    { readRepoFile: async () => null, writeRepoFile: async () => {} },
    {
      getPluginPath: () => join(dataDir, "plugin"),
    } as unknown as PosthogPluginService,
    mcp,
    noMcpApps,
    {
      onResume: () => () => {},
      preventSleep: () => () => {},
      hasBuiltInBattery: async () => false,
    },
    {
      resolve: (path) =>
        path.endsWith("/claude") ? claude : join(dataDir, path),
    },
    {
      version: "0.0.0-dev",
      isProduction: false,
      platform: process.platform,
      arch: process.arch,
    },
    { appDataPath: dataDir, logsPath: dataDir, logFolderPath: dataDir },
    {
      getAdditionalDirectories: async () => [],
    } as unknown as IWorkspaceRepository,
    {
      getWorktreeLocation: () => join(dataDir, "worktrees"),
    } as unknown as IWorkspaceSettings,
    logger,
  );
}

const claudeLoggedIn = async (): Promise<boolean> =>
  (
    await hasClaudeLogin({
      claudeCliPath: claudeBinary(),
      machineAuth: machineClaudeAuth(),
    })
  ).state === "logged-in";

const noMcpApps: AgentMcpApps = {
  handleDiscovery: async () => {},
  setServerConfigs: () => {},
  addServerConfigs: () => {},
  setConfigResolver: () => {},
  notifyToolCancelled: () => {},
  notifyToolInput: () => {},
  notifyToolResult: () => {},
  cleanup: async () => {},
};

export function createCloud(
  auth: TuiAuth,
  api: PostHogAPIClient,
): {
  runs: CloudRuns;
  chats: PiChats;
  control: (taskId: string, runId: string) => PiControl;
  startLocal: (id: string) => Promise<LocalAgent>;
  today: TodayClient;
} {
  let teamId: Promise<number> | null = null;
  const context = async () => {
    teamId ??= api.getCurrentUser().then(
      (user) => user.team.id,
      (error: unknown) => {
        teamId = null;
        throw error;
      },
    );
    return { apiHost: auth.apiHost, teamId: await teamId };
  };
  // The engine sends a Claude plan token only to a run the signed-in account started; the token file is that account's.
  const contextWithAccount = async (options?: { includeAccount?: boolean }) =>
    options?.includeAccount
      ? { ...(await context()), accountKey: auth.apiHost }
      : context();
  const engine = createCloudTaskEngine({
    auth: {
      authenticatedFetch: authenticatedFetch(auth),
      getCloudContext: contextWithAccount,
    },
    analytics: noAnalytics,
    logger,
    transcriptTailWindow: TRANSCRIPT_TAIL_WINDOW,
    claudeSubscriptionTokenStore: claudeTokenStore(),
  });
  const runs = new CloudRuns(
    engine,
    context,
    (taskId, runId, options) =>
      api.getTaskRunSessionLogsPage(taskId, runId, options),
    async (taskId) => (await api.getTaskUsage(taskId)).total_cost_usd,
    async (taskId, runId) => {
      const all = await api.listTaskRuns(taskId);
      const current = all.find((run) => run.id === runId);
      return all
        .filter(
          (run) =>
            run.id !== runId &&
            (!current || run.created_at < current.created_at),
        )
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .map((run) => run.id);
    },
  );
  const sendMessage = async (
    taskId: string,
    runId: string,
    content: string,
    artifactIds: string[],
  ) => {
    const result = await engine.sendCommand({
      taskId,
      runId,
      ...(await context()),
      method: "user_message",
      params: { content, artifact_ids: artifactIds, steer: true },
    });
    if (!result.success)
      throw new Error(result.error ?? "Couldn't send the message");
  };
  // The desktop app's uploader for cloud attachments. The TUI sends only images, never skills.
  const noSkills = (): never => {
    throw new Error("The TUI does not send skills");
  };
  const artifacts = new CloudArtifactService(
    async (filePath) => {
      try {
        return readFileSync(filePath).toString("base64");
      } catch {
        return null;
      }
    },
    noSkills,
    async () => [],
  );
  let projectId: number | null = null;
  const agentAuth: AgentAuth = {
    getValidAccessToken: async () => ({
      accessToken: await auth.getAccessToken(),
      apiHost: auth.apiHost,
    }),
    refreshAccessToken: async () => ({
      accessToken: await auth.refreshAccessToken(),
      apiHost: auth.apiHost,
    }),
    getOAuthCredentials: () => auth.oauthCredentials(),
    getState: () => ({ currentProjectId: projectId }),
    authenticatedFetch: (fetch, input, init) =>
      authenticatedFetch(auth, fetch)(input, init),
  };
  // createCloud runs once per sign-in, so the auth state the token service reads never changes.
  const gateway = new GatewayTokenService(
    {
      getValidAccessToken: agentAuth.getValidAccessToken,
      authenticatedFetch: authenticatedFetch(auth),
    },
    { goEnabled: true, override: null },
    {
      getState: () => ({
        status: "authenticated",
        cloudRegion: auth.region,
        currentProjectId: projectId,
      }),
      on: () => {},
    } as unknown as AuthService,
    logger,
  );
  // The same auth proxy, MCP servers and gateway attribution the desktop app gives local pi sessions.
  const authProxy = new AuthProxyService(
    { authenticatedFetch: authenticatedFetch(auth) },
    logger,
    gateway,
  );
  const mcp = new AgentAuthAdapter(
    agentAuth,
    authProxy,
    new McpProxyService(
      {
        authenticatedFetch: authenticatedFetch(auth),
        refreshAccessToken: () => auth.refreshAccessToken(),
      },
      logger,
    ),
    logger,
    gateway,
  );
  const piClients = new LocalPiRpcClientFactory(
    agentAuth,
    authProxy,
    mcp,
    noMcpApps,
    logger,
    gateway,
  );
  const localChats = new LocalChats();
  let claudeAgent: AgentService | undefined;
  const sendPi: PiCommand = async (input) =>
    engine.sendCommand({ ...input, ...(await context()) });
  return {
    runs,
    chats: new PiChats(
      api,
      sendMessage,
      currentRepository(),
      {
        toTask: (taskId, filePaths) =>
          artifacts.uploadTaskStagedAttachments(api, taskId, filePaths),
        toRun: (taskId, runId, filePaths) =>
          artifacts.uploadRunAttachments(api, taskId, runId, filePaths),
      },
      (taskId, runId, since) => runs.agentRestarted(taskId, runId, since),
    ),
    control: (taskId, runId) => piControl(sendPi, taskId, runId),
    today: new TodayClient(authenticatedFetch(auth), auth.apiHost, async () => {
      const user = await api.getCurrentUser();
      return {
        teamId: user.team.id,
        firstName: (user as { first_name?: string }).first_name || null,
      };
    }),
    // A local chat runs the harness in the folder the TUI started in, on the same PostHog login.
    startLocal: async (id) => {
      projectId = (await context()).teamId;
      // A chat keeps the agent it started with; only a new chat follows today's billing.
      const remembered = localChats.harnessOf(id);
      const start: LocalStart = remembered
        ? { harness: remembered }
        : localStartFor(loadPrefs().billing, {
            chatgptAccount: chatgptAccount(),
          });
      localChats.remember(id, start.harness);
      if (start.harness === "claude") {
        claudeAgent ??= createClaudeAgent(mcp, logger);
        const session = new ClaudeLocalSession(
          claudeAgent,
          {
            taskId: id,
            taskRunId: id,
            cwd: process.cwd(),
            apiHost: auth.apiHost,
            projectId,
          },
          claudeLoggedIn,
        );
        await session.start();
        return session;
      }
      const session = new LocalSession(
        await piClients.create({
          sessionFile: localChats.sessionFile(id),
          taskContext: { taskId: id, cwd: process.cwd() },
          model: start.harness === "pi" ? start.model : undefined,
        }),
        mcp,
      );
      await session.start();
      return session;
    },
  };
}

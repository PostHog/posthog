import "reflect-metadata";
import { useDevFlagsStore } from "@features/dev-toolbar/devFlagsStore";
import { TypedContainer } from "@inversifyjs/strongly-typed";
import type { TrpcRouter } from "@main/trpc/router";
import {
  CODE_REVIEW_WORKSPACE_CLIENT,
  REVERT_HUNK_SERVICE,
} from "@posthog/core/code-review/identifiers";
import type { CodeReviewWorkspaceClient } from "@posthog/core/code-review/revertHunkService";
import { RevertHunkService } from "@posthog/core/code-review/revertHunkService";
import {
  GITHUB_ISSUE_CLIENT,
  type GitHubIssueClient,
  NEW_TASK_LINK_RESOLVER,
} from "@posthog/core/deep-links/identifiers";
import { NewTaskLinkResolver } from "@posthog/core/deep-links/newTaskLinkResolver";
import { ExternalAppService } from "@posthog/core/external-apps/externalAppService";
import {
  EXTERNAL_APPS_FOCUS_COORDINATOR,
  EXTERNAL_APPS_SERVICE,
  EXTERNAL_APPS_WORKSPACE_CLIENT,
  type ExternalAppsWorkspaceClient,
} from "@posthog/core/external-apps/identifiers";
import { GitInteractionService } from "@posthog/core/git-interaction/gitInteractionService";
import {
  GIT_INTERACTION_EFFECTS,
  GIT_INTERACTION_SERVICE,
  GIT_WRITE_CLIENT,
} from "@posthog/core/git-interaction/identifiers";
import { LLM_GATEWAY_SERVICE } from "@posthog/core/llm-gateway/identifiers";
import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import type { LlmMessage } from "@posthog/core/llm-gateway/schemas";
import { LOCAL_MCP_WORKSPACE_CLIENT } from "@posthog/core/local-mcp/identifiers";
import type { LocalMcpWorkspaceClient } from "@posthog/core/local-mcp/localMcpImport";
import { PI_RUNNER } from "@posthog/core/pi-runtime/identifiers";
import { piRuntimeModule } from "@posthog/core/pi-runtime/pi-runtime.module";
import type { PiRunner } from "@posthog/core/pi-runtime/piRunner";
import { PI_SESSION_CLIENT } from "@posthog/core/pi-runtime/piSessionController";
import {
  CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL,
  CLOUD_ARTIFACT_READ_FILE_AS_BASE64,
  CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES,
} from "@posthog/core/sessions/cloudArtifactIdentifiers";
import {
  LOCAL_HANDOFF_DIALOG,
  LOCAL_HANDOFF_HOST,
  LOCAL_HANDOFF_NOTIFIER,
  LOCAL_HANDOFF_SERVICE,
  type LocalHandoffHost,
  LocalHandoffService,
} from "@posthog/core/sessions/localHandoffService";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { sessionsModule } from "@posthog/core/sessions/sessions.module";
import {
  TITLE_GENERATOR_FILE_READ_CLIENT,
  TITLE_GENERATOR_LOGGER,
} from "@posthog/core/sessions/titleGeneratorIdentifiers";
import { SKILLS_WORKSPACE_CLIENT } from "@posthog/core/skills/identifiers";
import type { SkillsWorkspaceClient } from "@posthog/core/skills/teamSkillsService";
import {
  TASK_CREATION_EFFECTS,
  TASK_CREATION_HOST,
  WORKSPACE_SETUP_SAGA,
} from "@posthog/core/task-detail/identifiers";
import type { ITaskCreationHost } from "@posthog/core/task-detail/taskCreationHost";
import {
  TASK_SERVICE,
  TaskService,
} from "@posthog/core/task-detail/taskService";
import { WorkspaceSetupSaga } from "@posthog/core/task-detail/workspaceSetupSaga";
import {
  TASK_DELETION_HOST,
  TASK_DELETION_SERVICE,
  TASK_DELETION_WORKSPACE_CLIENT,
} from "@posthog/core/tasks/identifiers";
import { TaskDeletionService } from "@posthog/core/tasks/taskDeletionService";
import {
  SHELL_PROCESS_READER,
  type ShellProcessReader,
} from "@posthog/core/terminal/identifiers";
import { terminalCoreModule } from "@posthog/core/terminal/terminal.module";
import {
  WORKSPACE_SETUP_GIT_CLIENT,
  WORKSPACE_SETUP_SERVICE,
} from "@posthog/core/workspace/identifiers";
import { WorkspaceSetupService } from "@posthog/core/workspace/WorkspaceSetupService";
import { setRootContainer } from "@posthog/di/container";
import { HOST_TRPC_CLIENT } from "@posthog/host-router/client";
import { TrpcPiSessionClient } from "@posthog/host-router/pi-session-client";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "@posthog/ui/features/browser-tabs/browserTabsClient";
import {
  REVIEW_HOST,
  type ReviewHost,
} from "@posthog/ui/features/code-review/reviewHost";
import {
  CONNECTIVITY_CLIENT,
  type ConnectivityClient,
} from "@posthog/ui/features/connectivity/connectivityClient";
import {
  DISCORD_PRESENCE_CLIENT,
  type DiscordPresenceClient,
} from "@posthog/ui/features/discord-presence/identifiers";
import { FocusStoreCoordinator } from "@posthog/ui/features/external-apps/focusCoordinator";
import { focusDeps } from "@posthog/ui/features/focus/focusAdapter";
import { FOCUS_CONTROLLER_DEPS } from "@posthog/ui/features/focus/focusClient";
import {
  gitInteractionEffects,
  gitWriteClient,
} from "@posthog/ui/features/git-interaction/gitInteractionAdapter";
import { McpAppHost } from "@posthog/ui/features/mcp-apps/components/McpAppHost";
import { McpToolBlock } from "@posthog/ui/features/mcp-apps/components/McpToolBlock";
import {
  MCP_APP_HOST_COMPONENT,
  MCP_SANDBOX_PROXY_URL,
} from "@posthog/ui/features/mcp-apps/identifiers";
import { MCP_TOOL_BLOCK_COMPONENT } from "@posthog/ui/features/sessions/components/session-update/identifiers";
import {
  localHandoffDialog,
  localHandoffNotifier,
} from "@posthog/ui/features/sessions/localHandoffService";
import { getSessionService } from "@posthog/ui/features/sessions/sessionServiceHost";
import {
  DEV_MODE_CLIENT,
  type DevModeClient,
} from "@posthog/ui/features/settings/devModeClient";
import { taskCreationEffects } from "@posthog/ui/features/task-detail/taskCreationEffectsImpl";
import { TrpcTaskCreationHost } from "@posthog/ui/features/task-detail/taskCreationHostImpl";
import {
  SHELL_CLIENT,
  type ShellClient,
} from "@posthog/ui/features/terminal/shellClient";
import { updatesClient } from "@posthog/ui/features/updates/updatesAdapter";
import { UPDATES_CLIENT } from "@posthog/ui/features/updates/updatesClient";
import {
  ANALYTICS_TRACKER,
  type AnalyticsTracker,
} from "@posthog/ui/shell/analytics";
import { DIFF_WORKER_FACTORY } from "@posthog/ui/shell/diffWorkerHost";
import { HOST_LOGGER } from "@posthog/ui/shell/logger";
import { posthogAnalyticsTracker } from "@posthog/ui/shell/posthogAnalyticsImpl";
import {
  diffWorkerFactory,
  reviewHost,
} from "@renderer/features/code-review/reviewHost";
import {
  taskDeletionHost,
  taskDeletionWorkspaceClient,
} from "@renderer/platform-adapters/task-deletion";
import { trpcClient } from "@renderer/trpc";
import { hostTrpcClient } from "@renderer/trpc/client";
import type { TRPCClient } from "@trpc/client";
import { hostLog, logger } from "@utils/logger";
import { TrpcPiRunner } from "../platform-adapters/trpc-pi-runner";
import type { RendererBindings } from "./bindings";
import { TASK_SERVICE as RENDERER_TASK_SERVICE, TRPC_CLIENT } from "./tokens";

/**
 * Renderer process dependency injection container
 */
export const container = new TypedContainer<RendererBindings>({
  defaultScope: "Singleton",
});

setRootContainer(container);

container.bind(HOST_LOGGER).toConstantValue(hostLog);

// Bind infrastructure
container.bind<TRPCClient<TrpcRouter>>(TRPC_CLIENT).toConstantValue(trpcClient);

container.bind(HOST_TRPC_CLIENT).toConstantValue(hostTrpcClient);

container.bind(UPDATES_CLIENT).toConstantValue(updatesClient);

// dev mode client — exposes the dev-toolbar flag store to the shared settings UI
const devModeClient: DevModeClient = {
  getDevMode: () => useDevFlagsStore.getState().devMode,
  setDevMode: (enabled) => useDevFlagsStore.getState().setDevMode(enabled),
  onDevModeChanged: (listener) =>
    useDevFlagsStore.subscribe((state) => listener(state.devMode)),
};
container.bind(DEV_MODE_CLIENT).toConstantValue(devModeClient);

// connectivity client — passthrough over the renderer host client
const connectivityClient: ConnectivityClient = {
  getStatus: () => trpcClient.connectivity.getStatus.query(),
  checkNow: () => trpcClient.connectivity.checkNow.mutate(),
  onStatusChange: (sub) =>
    trpcClient.connectivity.onStatusChange.subscribe(undefined, sub),
};
container.bind(CONNECTIVITY_CLIENT).toConstantValue(connectivityClient);

// browser tabs client — passthrough over the renderer host client
const browserTabsClient: BrowserTabsClient = {
  getSnapshot: () => trpcClient.browserTabs.getSnapshot.query(),
  getPrimaryWindowId: () => trpcClient.browserTabs.getPrimaryWindowId.query(),
  openOrFocus: (input) => trpcClient.browserTabs.openOrFocus.mutate(input),
  newBlankTab: (input) => trpcClient.browserTabs.newBlankTab.mutate(input),
  setTabTarget: (input) => trpcClient.browserTabs.setTabTarget.mutate(input),
  close: (tabId) => trpcClient.browserTabs.close.mutate({ tabId }),
  setActiveTab: (input) => trpcClient.browserTabs.setActiveTab.mutate(input),
  onSnapshotChange: (sub) =>
    trpcClient.browserTabs.onSnapshotChange.subscribe(undefined, sub),
};
container.bind(BROWSER_TABS_CLIENT).toConstantValue(browserTabsClient);

// discord presence client — passthrough over the local main-process router
const discordPresenceClient: DiscordPresenceClient = {
  getState: () => trpcClient.discordPresence.getState.query(),
  setEnabled: async (enabled) => {
    await trpcClient.discordPresence.setEnabled.mutate({ enabled });
  },
  setShowTaskTitle: async (value) => {
    await trpcClient.discordPresence.setShowTaskTitle.mutate({ value });
  },
  setShowRepoName: async (value) => {
    await trpcClient.discordPresence.setShowRepoName.mutate({ value });
  },
  setActivity: async (intent) => {
    await trpcClient.discordPresence.setActivity.mutate(intent);
  },
  onStatusChanged: (onData) => {
    const sub = trpcClient.discordPresence.onStatusChanged.subscribe(
      undefined,
      { onData },
    );
    return () => sub.unsubscribe();
  },
};
container.bind(DISCORD_PRESENCE_CLIENT).toConstantValue(discordPresenceClient);

// terminal shell client
const shellClient: ShellClient = {
  write: async (input) => {
    await trpcClient.shell.write.mutate(input);
  },
  check: (input) => trpcClient.shell.check.query(input),
  destroy: async (input) => {
    await trpcClient.shell.destroy.mutate(input);
  },
  create: async (input) => {
    await trpcClient.shell.create.mutate(input);
  },
  createCommand: async (input) => {
    await trpcClient.shell.createCommand.mutate(input);
  },
  resize: async (input) => {
    await trpcClient.shell.resize.mutate(input);
  },
  getProcess: async (input) =>
    (await trpcClient.shell.getProcess.query(input)) ?? null,
  execute: (input) => trpcClient.shell.execute.mutate(input),
  openExternal: async (input) => {
    await trpcClient.os.openExternal.mutate(input);
  },
  onData: (sessionId, onEvent) =>
    trpcClient.shell.onData.subscribe({ sessionId }, { onData: onEvent }),
  onExit: (sessionId, onEvent) =>
    trpcClient.shell.onExit.subscribe({ sessionId }, { onData: onEvent }),
};
container.bind(SHELL_CLIENT).toConstantValue(shellClient);

// focus controller deps
container.bind(FOCUS_CONTROLLER_DEPS).toConstantValue(focusDeps);

// code-review host (diff worker factory + expanded-review sidebar)
container.bind(DIFF_WORKER_FACTORY).toConstantValue(diffWorkerFactory);
container.bind<ReviewHost>(REVIEW_HOST).toConstantValue(reviewHost);

// sessions MCP tool renderer slot
container.bind(MCP_TOOL_BLOCK_COMPONENT).toConstantValue(McpToolBlock);

// interactive MCP App iframe host + its electron isolated-origin sandbox URL
container.bind(MCP_APP_HOST_COMPONENT).toConstantValue(McpAppHost);
container
  .bind(MCP_SANDBOX_PROXY_URL)
  .toConstantValue(() => "mcp-sandbox://proxy");

// terminal shell process reader + core module
container.bind<ShellProcessReader>(SHELL_PROCESS_READER).toConstantValue({
  getProcess: async (input) =>
    (await trpcClient.shell.getProcess.query(input)) ?? null,
});
container.load(terminalCoreModule);

// analytics tracker
container
  .bind<AnalyticsTracker>(ANALYTICS_TRACKER)
  .toConstantValue(posthogAnalyticsTracker);

// Bind services
container.bind<ITaskCreationHost>(TASK_CREATION_HOST).to(TrpcTaskCreationHost);
container.bind<PiRunner>(PI_RUNNER).to(TrpcPiRunner);
container.bind(PI_SESSION_CLIENT).to(TrpcPiSessionClient);
container.load(piRuntimeModule);
container.bind(TASK_CREATION_EFFECTS).toConstantValue(taskCreationEffects);
container.bind<TaskService>(RENDERER_TASK_SERVICE).to(TaskService);
container.bind<TaskService>(TASK_SERVICE).toService(RENDERER_TASK_SERVICE);
container
  .bind<WorkspaceSetupSaga>(WORKSPACE_SETUP_SAGA)
  .to(WorkspaceSetupSaga)
  .inSingletonScope();
container
  .bind<SessionService>(SESSION_SERVICE)
  .toDynamicValue(() => getSessionService())
  .inSingletonScope();
container.bind<LocalHandoffHost>(LOCAL_HANDOFF_HOST).toConstantValue({
  getRepositoryByRemoteUrl: (input) =>
    trpcClient.folders.getRepositoryByRemoteUrl.query(input),
  selectDirectory: () => trpcClient.os.selectDirectory.query(),
  addFolder: (input) => trpcClient.folders.addFolder.mutate(input),
});
container.bind(LOCAL_HANDOFF_DIALOG).toConstantValue(localHandoffDialog);
container.bind(LOCAL_HANDOFF_NOTIFIER).toConstantValue(localHandoffNotifier);
container
  .bind<LocalHandoffService>(LOCAL_HANDOFF_SERVICE)
  .to(LocalHandoffService)
  .inSingletonScope();

// git-interaction
container.bind(GIT_WRITE_CLIENT).toConstantValue(gitWriteClient);
container.bind(GIT_INTERACTION_EFFECTS).toConstantValue(gitInteractionEffects);
container
  .bind(GIT_INTERACTION_SERVICE)
  .to(GitInteractionService)
  .inSingletonScope();

// tasks (deletion)
container
  .bind(TASK_DELETION_WORKSPACE_CLIENT)
  .toConstantValue(taskDeletionWorkspaceClient);
container.bind(TASK_DELETION_HOST).toConstantValue(taskDeletionHost);
container
  .bind<TaskDeletionService>(TASK_DELETION_SERVICE)
  .to(TaskDeletionService)
  .inSingletonScope();

// external-apps
container.bind(EXTERNAL_APPS_WORKSPACE_CLIENT).toConstantValue({
  openInApp: (appId: string, targetPath: string) =>
    hostTrpcClient.externalApps.openInApp.mutate({ appId, targetPath }),
  setLastUsed: async (appId: string) => {
    await hostTrpcClient.externalApps.setLastUsed.mutate({ appId });
  },
  getDetectedApps: () => hostTrpcClient.externalApps.getDetectedApps.query(),
  copyPath: async (targetPath: string) => {
    await hostTrpcClient.externalApps.copyPath.mutate({ targetPath });
  },
} satisfies ExternalAppsWorkspaceClient);
container
  .bind(EXTERNAL_APPS_FOCUS_COORDINATOR)
  .to(FocusStoreCoordinator)
  .inSingletonScope();
container.bind(EXTERNAL_APPS_SERVICE).to(ExternalAppService).inSingletonScope();

// workspace setup
container.bind(WORKSPACE_SETUP_GIT_CLIENT).toConstantValue({
  detectRepo: (args: { directoryPath: string }) =>
    trpcClient.git.detectRepo.query(args),
});
container
  .bind(WORKSPACE_SETUP_SERVICE)
  .to(WorkspaceSetupService)
  .inSingletonScope();

// deep-links
container.bind(GITHUB_ISSUE_CLIENT).toConstantValue({
  getGithubIssue: (owner, repo, issueNumber) =>
    trpcClient.git.getGithubIssue.query({
      owner,
      repo,
      number: issueNumber,
    }),
} satisfies GitHubIssueClient);
container
  .bind(NEW_TASK_LINK_RESOLVER)
  .to(NewTaskLinkResolver)
  .inSingletonScope();

// code-review
container.bind(CODE_REVIEW_WORKSPACE_CLIENT).toConstantValue({
  getFileAtHead: (directoryPath: string, filePath: string) =>
    trpcClient.git.getFileAtHead.query({ directoryPath, filePath }),
  readRepoFile: (repoPath: string, filePath: string) =>
    trpcClient.fs.readRepoFile.query({ repoPath, filePath }),
  writeRepoFile: async (
    repoPath: string,
    filePath: string,
    content: string,
  ) => {
    await trpcClient.fs.writeRepoFile.mutate({ repoPath, filePath, content });
  },
} satisfies CodeReviewWorkspaceClient);
container.bind(REVERT_HUNK_SERVICE).to(RevertHunkService).inSingletonScope();

// local MCP servers (~/.claude.json), read for cloud-import classification
container.bind(LOCAL_MCP_WORKSPACE_CLIENT).toConstantValue({
  listLocalMcpServers: (cwd?: string) =>
    trpcClient.localMcp.list.query({ cwd }),
} satisfies LocalMcpWorkspaceClient);

// skills (team publish/install reach workspace-server through this slice)
container.bind(SKILLS_WORKSPACE_CLIENT).toConstantValue({
  exportSkill: (skillPath: string) =>
    trpcClient.skills.export.query({ skillPath }),
  installTeamSkill: (input) => trpcClient.skills.installTeamSkill.mutate(input),
} satisfies SkillsWorkspaceClient);

// sessions (cloud-artifact + title-generator)
container.load(sessionsModule);
container
  .bind(CLOUD_ARTIFACT_READ_FILE_AS_BASE64)
  .toConstantValue((filePath: string) =>
    trpcClient.fs.readFileAsBase64.query({ filePath }),
  );
container
  .bind(CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL)
  .toConstantValue((skillBundleRef) =>
    hostTrpcClient.skills.bundleLocal.query(skillBundleRef),
  );
container
  .bind(CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES)
  .toConstantValue((skillBundleRefs) =>
    hostTrpcClient.skills.resolveDependencies.query(skillBundleRefs),
  );
container.bind(LLM_GATEWAY_SERVICE).toConstantValue({
  prompt: (
    messages: LlmMessage[],
    options: { system?: string; maxTokens?: number; model?: string } = {},
  ) =>
    trpcClient.llmGateway.prompt.mutate({
      messages,
      system: options.system,
      maxTokens: options.maxTokens,
      model: options.model,
    }),
} as unknown as LlmGatewayService);
container.bind(TITLE_GENERATOR_FILE_READ_CLIENT).toConstantValue({
  readAbsoluteFile: (filePath: string) =>
    trpcClient.fs.readAbsoluteFile.query({ filePath }),
});
container
  .bind(TITLE_GENERATOR_LOGGER)
  .toConstantValue(logger.scope("title-generator"));

export function get<T>(token: symbol): T {
  return container.get<T>(token);
}

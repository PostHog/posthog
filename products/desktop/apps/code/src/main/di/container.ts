import "reflect-metadata";

import { readFile as fsReadFile, stat as fsStat } from "node:fs/promises";
import { TypedContainer } from "@inversifyjs/strongly-typed";
import { DEFAULT_GATEWAY_MODEL } from "@posthog/agent/gateway-models";
import {
  getGatewayUsageUrl,
  getLlmGatewayUrl,
} from "@posthog/agent/posthog-api";
import { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import {
  AUTH_CONNECTIVITY,
  AUTH_OAUTH_FLOW_SERVICE,
  AUTH_PREFERENCE_STORE,
  AUTH_SESSION_STORE,
  AUTH_TOKEN_CIPHER,
  AUTH_TOKEN_OVERRIDE,
} from "@posthog/core/auth/identifiers";
import { canvasCoreModule } from "@posthog/core/canvas/canvas.module";
import { cloudTaskModule } from "@posthog/core/cloud-task/cloud-task.module";
import {
  CLOUD_TASK_AUTH,
  CLOUD_TASK_SERVICE,
  MCP_RELAY_EXECUTOR,
} from "@posthog/core/cloud-task/identifiers";
import { contextMenuCoreModule } from "@posthog/core/context-menu/context-menu.module";
import {
  CONTEXT_MENU_CONTROLLER,
  CONTEXT_MENU_EXTERNAL_APPS_SERVICE,
} from "@posthog/core/context-menu/identifiers";
import { FocusHostService } from "@posthog/core/focus/focus-service";
import { FocusServiceEvent } from "@posthog/core/focus/identifiers";
import { gitHostModule } from "@posthog/core/git/git-host.module";
import type {
  GitWorkspaceLookup,
  HostGitWorkspaceClient,
} from "@posthog/core/git/host-git";
import {
  GIT_AGENT_SERVICE,
  GIT_WORKSPACE_CLIENT,
  GIT_WORKSPACE_LOOKUP,
} from "@posthog/core/git/identifiers";
import { gitPrModule } from "@posthog/core/git-pr/git-pr.module";
import { GIT_DIFF_SOURCE } from "@posthog/core/git-pr/identifiers";
import { handoffModule } from "@posthog/core/handoff/handoff.module";
import { HANDOFF_HOST } from "@posthog/core/handoff/identifiers";
import { integrationsModule } from "@posthog/core/integrations/integrations.module";
import { ApprovalLinkService } from "@posthog/core/links/approval-link";
import { CanvasLinkService } from "@posthog/core/links/canvas-link";
import { ChannelLinkService } from "@posthog/core/links/channel-link";
import {
  APPROVAL_LINK_SERVICE,
  CANVAS_LINK_SERVICE,
  CHANNEL_LINK_SERVICE,
  INBOX_LINK_SERVICE,
  NEW_TASK_LINK_SERVICE,
  OPEN_TARGET_LINK_SERVICE,
  SCOUT_LINK_SERVICE,
  TASK_LINK_SERVICE,
} from "@posthog/core/links/identifiers";
import { InboxLinkService } from "@posthog/core/links/inbox-link";
import { NewTaskLinkService } from "@posthog/core/links/new-task-link";
import { OpenTargetLinkService } from "@posthog/core/links/open-target-link";
import { ScoutLinkService } from "@posthog/core/links/scout-link";
import { TaskLinkService } from "@posthog/core/links/task-link";
import {
  LLM_GATEWAY_HOST,
  LLM_GATEWAY_SERVICE,
} from "@posthog/core/llm-gateway/identifiers";
import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import { llmGatewayModule } from "@posthog/core/llm-gateway/llm-gateway.module";
import { MCP_APPS_SERVICE } from "@posthog/core/mcp-apps/identifiers";
import { mcpAppsModule } from "@posthog/core/mcp-apps/mcp-apps.module";
import { NOTIFICATION_SERVICE } from "@posthog/core/notification/identifiers";
import { NotificationService } from "@posthog/core/notification/notification";
import {
  OAUTH_HOST,
  type OAuthCallbackReceiver,
} from "@posthog/core/oauth/identifiers";
import { oauthModule } from "@posthog/core/oauth/oauth.module";
import { PROVISIONING_SERVICE } from "@posthog/core/provisioning/identifiers";
import { ProvisioningService } from "@posthog/core/provisioning/provisioning";
import { SLEEP_SERVICE } from "@posthog/core/sleep/identifiers";
import { SleepService } from "@posthog/core/sleep/sleep";
import { UI_AUTH } from "@posthog/core/ui/identifiers";
import { uiModule } from "@posthog/core/ui/ui.module";
import {
  UPDATE_LIFECYCLE_SERVICE,
  UPDATES_SERVICE,
} from "@posthog/core/updates/identifiers";
import { updatesCoreModule } from "@posthog/core/updates/updates.module";
import { USAGE_HOST } from "@posthog/core/usage/identifiers";
import { usageMonitorModule } from "@posthog/core/usage/usage-monitor.module";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import { listFilesContainingText } from "@posthog/git/queries";
import {
  GIT_PR_STATUS_PROVIDER,
  type IGitPrStatus,
} from "@posthog/host-router/ports/git-pr-status";
import { ANALYTICS_SERVICE } from "@posthog/platform/analytics";
import { APP_LIFECYCLE_SERVICE } from "@posthog/platform/app-lifecycle";
import { APP_META_SERVICE } from "@posthog/platform/app-meta";
import { APP_METRICS_SERVICE } from "@posthog/platform/app-metrics";
import { BUNDLED_RESOURCES_SERVICE } from "@posthog/platform/bundled-resources";
import { CLIPBOARD_SERVICE } from "@posthog/platform/clipboard";
import { CONTEXT_MENU_SERVICE } from "@posthog/platform/context-menu";
import { CRYPTO_SERVICE } from "@posthog/platform/crypto";
import { DEEP_LINK_SERVICE } from "@posthog/platform/deep-link";
import { DEV_HOST_ACTIONS_SERVICE } from "@posthog/platform/dev-host-actions";
import { DIALOG_SERVICE } from "@posthog/platform/dialog";
import { FILE_ICON_SERVICE } from "@posthog/platform/file-icon";
import { IMAGE_PROCESSOR_SERVICE } from "@posthog/platform/image-processor";
import { MAIN_WINDOW_SERVICE } from "@posthog/platform/main-window";
import { NOTIFIER_SERVICE } from "@posthog/platform/notifier";
import { POWER_MANAGER_SERVICE } from "@posthog/platform/power-manager";
import { SECURE_STORAGE_SERVICE } from "@posthog/platform/secure-storage";
import { STORAGE_PATHS_SERVICE } from "@posthog/platform/storage-paths";
import { UPDATER_SERVICE } from "@posthog/platform/updater";
import { URL_LAUNCHER_SERVICE } from "@posthog/platform/url-launcher";
import { WORKSPACE_SETTINGS_SERVICE } from "@posthog/platform/workspace-settings";
import type { WorkspaceClient } from "@posthog/workspace-client/client";
import { databaseModule } from "@posthog/workspace-server/db/db.module";
import {
  ARCHIVE_REPOSITORY,
  AUTH_PREFERENCE_REPOSITORY,
  AUTH_SESSION_REPOSITORY,
  DATABASE_SERVICE,
  DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY,
  REPOSITORY_REPOSITORY,
  SUSPENSION_REPOSITORY,
  WORKSPACE_REPOSITORY,
  WORKTREE_REPOSITORY,
} from "@posthog/workspace-server/db/identifiers";
import { repositoriesModule } from "@posthog/workspace-server/db/repositories.module";
import { GIT_SERVICE as WS_GIT_SERVICE } from "@posthog/workspace-server/di/tokens";
import { additionalDirectoriesModule } from "@posthog/workspace-server/services/additional-directories/additional-directories.module";
import type { AgentService } from "@posthog/workspace-server/services/agent/agent";
import { agentModule } from "@posthog/workspace-server/services/agent/agent.module";
import {
  AGENT_AUTH,
  AGENT_LOGGER,
  AGENT_MCP_APPS,
  AGENT_REPO_FILES,
  AGENT_SERVICE,
  AGENT_SLEEP_COORDINATOR,
} from "@posthog/workspace-server/services/agent/identifiers";
import { AgentServiceEvent } from "@posthog/workspace-server/services/agent/schemas";
import { archiveModule } from "@posthog/workspace-server/services/archive/archive.module";
import {
  ARCHIVE_FILE_WATCHER,
  ARCHIVE_SESSION_CANCELLER,
} from "@posthog/workspace-server/services/archive/identifiers";
import { authProxyModule } from "@posthog/workspace-server/services/auth-proxy/auth-proxy.module";
import { AUTH_PROXY_AUTH } from "@posthog/workspace-server/services/auth-proxy/identifiers";
import { browserTabsModule } from "@posthog/workspace-server/services/browser-tabs/browser-tabs.module";
import { claudeCliSessionsModule } from "@posthog/workspace-server/services/claude-cli-sessions/claude-cli-sessions.module";
import { enrichmentModule } from "@posthog/workspace-server/services/enrichment/enrichment.module";
import {
  ENRICHMENT_AUTH,
  ENRICHMENT_FILE_READER,
} from "@posthog/workspace-server/services/enrichment/identifiers";
import { externalAppsModule } from "@posthog/workspace-server/services/external-apps/external-apps.module";
import {
  EXTERNAL_APPS_SERVICE,
  EXTERNAL_APPS_STORE,
} from "@posthog/workspace-server/services/external-apps/identifiers";
import type { ExternalAppsPreferences } from "@posthog/workspace-server/services/external-apps/types";
import { foldersModule } from "@posthog/workspace-server/services/folders/folders.module";
import { GitService } from "@posthog/workspace-server/services/git/service";
import { TaskPrStatusService } from "@posthog/workspace-server/services/git/task-pr-status";
import {
  HANDOFF_GIT_GATEWAY,
  HANDOFF_LOG_GATEWAY,
} from "@posthog/workspace-server/services/handoff/identifiers";
import type { HandoffGitGateway } from "@posthog/workspace-server/services/handoff/ports";
import { HandoffHostService } from "@posthog/workspace-server/services/handoff/service";
import { LOGS_SERVICE } from "@posthog/workspace-server/services/local-logs/identifiers";
import { localMcpModule } from "@posthog/workspace-server/services/local-mcp/local-mcp.module";
import { mcpCallbackModule } from "@posthog/workspace-server/services/mcp-callback/mcp-callback.module";
import { MCP_PROXY_AUTH } from "@posthog/workspace-server/services/mcp-proxy/identifiers";
import { mcpProxyModule } from "@posthog/workspace-server/services/mcp-proxy/mcp-proxy.module";
import { MCP_RELAY_SERVICE } from "@posthog/workspace-server/services/mcp-relay/identifiers";
import { mcpRelayModule } from "@posthog/workspace-server/services/mcp-relay/mcp-relay.module";
import { OAUTH_CALLBACK_SERVER } from "@posthog/workspace-server/services/oauth-callback/identifiers";
import { oauthCallbackModule } from "@posthog/workspace-server/services/oauth-callback/oauth-callback.module";
import { onboardingImportModule } from "@posthog/workspace-server/services/onboarding-import/onboarding-import.module";
import { osModule } from "@posthog/workspace-server/services/os/os.module";
import {
  PI_RPC_CLIENT_FACTORY,
  PI_RUNTIME_FACTORY,
  PI_SESSION_SERVICE,
} from "@posthog/workspace-server/services/pi-session/identifiers";
import type { PiSessionService } from "@posthog/workspace-server/services/pi-session/pi-session";
import { piSessionModule } from "@posthog/workspace-server/services/pi-session/pi-session.module";
import { POSTHOG_PLUGIN_SERVICE } from "@posthog/workspace-server/services/posthog-plugin/identifiers";
import { posthogPluginModule } from "@posthog/workspace-server/services/posthog-plugin/posthog-plugin.module";
import { PROCESS_TRACKING_SERVICE } from "@posthog/workspace-server/services/process-tracking/identifiers";
import { processTrackingModule } from "@posthog/workspace-server/services/process-tracking/process-tracking.module";
import { releaseFeedModule } from "@posthog/workspace-server/services/release-feed/release-feed.module";
import { SECURE_STORE_SERVICE } from "@posthog/workspace-server/services/secure-store/identifiers";
import { shellModule } from "@posthog/workspace-server/services/shell/shell.module";
import { skillsModule } from "@posthog/workspace-server/services/skills/skills.module";
import { skillsMarketplaceModule } from "@posthog/workspace-server/services/skills-marketplace/skills-marketplace.module";
import { SPEECH_SYNTHESIZER_SERVICE } from "@posthog/workspace-server/services/speech/identifiers";
import {
  SUSPENSION_FILE_WATCHER,
  SUSPENSION_SERVICE,
  SUSPENSION_SESSION_CANCELLER,
} from "@posthog/workspace-server/services/suspension/identifiers";
import { suspensionModule } from "@posthog/workspace-server/services/suspension/suspension.module";
import { FileWatcherEventKind } from "@posthog/workspace-server/services/watcher/schemas";
import { WATCHER_REGISTRY_SERVICE } from "@posthog/workspace-server/services/watcher-registry/identifiers";
import { watcherRegistryModule } from "@posthog/workspace-server/services/watcher-registry/watcher-registry.module";
import {
  WORKSPACE_AGENT,
  WORKSPACE_FILE_WATCHER,
  WORKSPACE_FOCUS,
  WORKSPACE_PROVISIONING,
  WORKSPACE_SERVICE,
} from "@posthog/workspace-server/services/workspace/identifiers";
import type {
  WorkspaceAgent,
  WorkspaceFileWatcher,
  WorkspaceFocus,
  WorkspaceProvisioning,
} from "@posthog/workspace-server/services/workspace/ports";
import type { WorkspaceService } from "@posthog/workspace-server/services/workspace/workspace";
import { workspaceModule } from "@posthog/workspace-server/services/workspace/workspace.module";
import { workspaceMetadataModule } from "@posthog/workspace-server/services/workspace-metadata/workspace-metadata.module";
import ExternalAppsStoreImpl from "electron-store";
import type { FileWatcherBridge } from "../index";
import { DesktopPiRpcClientFactory } from "../platform-adapters/desktop-pi-rpc-client-factory";
import { DesktopPiRuntimeFactory } from "../platform-adapters/desktop-pi-runtime-factory";
import { ElectronAppLifecycle } from "../platform-adapters/electron-app-lifecycle";
import { ElectronAppMeta } from "../platform-adapters/electron-app-meta";
import { ElectronAppMetrics } from "../platform-adapters/electron-app-metrics";
import { ElectronBundledResources } from "../platform-adapters/electron-bundled-resources";
import { ElectronClipboard } from "../platform-adapters/electron-clipboard";
import { ElectronContextMenu } from "../platform-adapters/electron-context-menu";
import { ElectronCrypto } from "../platform-adapters/electron-crypto";
import { ElectronDevHostActions } from "../platform-adapters/electron-dev-host-actions";
import { ElectronDialog } from "../platform-adapters/electron-dialog";
import { ElectronFileIcon } from "../platform-adapters/electron-file-icon";
import { ElectronImageProcessor } from "../platform-adapters/electron-image-processor";
import { ElectronMainWindow } from "../platform-adapters/electron-main-window";
import { ElectronNotifier } from "../platform-adapters/electron-notifier";
import { ElectronPowerManager } from "../platform-adapters/electron-power-manager";
import { ElectronSecureStorage } from "../platform-adapters/electron-secure-storage";
import { ElectronStoragePaths } from "../platform-adapters/electron-storage-paths";
import { ElectronUpdater } from "../platform-adapters/electron-updater";
import { ElectronUrlLauncher } from "../platform-adapters/electron-url-launcher";
import { electronUsageThresholdStore } from "../platform-adapters/electron-usage-threshold-store";
import { ElectronWorkspaceSettings } from "../platform-adapters/electron-workspace-settings";
import { posthogNodeAnalytics } from "../platform-adapters/posthog-analytics";
import { AppLifecycleService } from "../services/app-lifecycle/service";
import {
  AuthPreferencePortAdapter,
  AuthSessionPortAdapter,
  ConnectivityPortAdapter,
  OAuthFlowPortAdapter,
  TokenCipherPortAdapter,
} from "../services/auth/port-adapters";
import { DeepLinkService } from "../services/deep-link/service";
import { DevActionsService } from "../services/dev-actions/service";
import { DevFlagsService } from "../services/dev-flags/service";
import { DevLogsService } from "../services/dev-logs/service";
import { DevMetricsService } from "../services/dev-metrics/service";
import { DevNetworkService } from "../services/dev-network/service";
import { DiscordPresenceService } from "../services/discord-presence/service";
import { EncryptionService } from "../services/encryption/service";
import { SecureStoreService } from "../services/secure-store/service";
import { settingsStore } from "../services/settingsStore";
import { ElevenLabsSpeechService } from "../services/speech/service";
import { WorkspaceServerService } from "../services/workspace-server/service";
import { getUserDataDir, isDevBuild } from "../utils/env";
import { logger } from "../utils/logger";
import { rendererStore } from "../utils/store";
import type { MainBindings } from "./bindings";
import {
  APP_LIFECYCLE_SERVICE as MAIN_APP_LIFECYCLE_SERVICE,
  APPROVAL_LINK_SERVICE as MAIN_APPROVAL_LINK_SERVICE,
  ARCHIVE_REPOSITORY as MAIN_ARCHIVE_REPOSITORY,
  AUTH_PREFERENCE_REPOSITORY as MAIN_AUTH_PREFERENCE_REPOSITORY,
  AUTH_SERVICE as MAIN_AUTH_SERVICE,
  AUTH_SESSION_REPOSITORY as MAIN_AUTH_SESSION_REPOSITORY,
  CANVAS_LINK_SERVICE as MAIN_CANVAS_LINK_SERVICE,
  CHANNEL_LINK_SERVICE as MAIN_CHANNEL_LINK_SERVICE,
  CLOUD_TASK_SERVICE as MAIN_CLOUD_TASK_SERVICE,
  CONTEXT_MENU_SERVICE as MAIN_CONTEXT_MENU_SERVICE,
  DATABASE_SERVICE as MAIN_DATABASE_SERVICE,
  DEEP_LINK_SERVICE as MAIN_DEEP_LINK_SERVICE,
  DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY as MAIN_DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY,
  DEV_ACTIONS_SERVICE as MAIN_DEV_ACTIONS_SERVICE,
  DEV_FLAGS_SERVICE as MAIN_DEV_FLAGS_SERVICE,
  DEV_LOGS_SERVICE as MAIN_DEV_LOGS_SERVICE,
  DEV_METRICS_SERVICE as MAIN_DEV_METRICS_SERVICE,
  DEV_NETWORK_SERVICE as MAIN_DEV_NETWORK_SERVICE,
  DISCORD_PRESENCE_SERVICE as MAIN_DISCORD_PRESENCE_SERVICE,
  ENCRYPTION_SERVICE as MAIN_ENCRYPTION_SERVICE,
  EXTERNAL_APPS_SERVICE as MAIN_EXTERNAL_APPS_SERVICE,
  FILE_WATCHER_SERVICE as MAIN_FILE_WATCHER_SERVICE,
  FS_SERVICE as MAIN_FS_SERVICE,
  INBOX_LINK_SERVICE as MAIN_INBOX_LINK_SERVICE,
  LLM_GATEWAY_SERVICE as MAIN_LLM_GATEWAY_SERVICE,
  MCP_APPS_SERVICE as MAIN_MCP_APPS_SERVICE,
  NEW_TASK_LINK_SERVICE as MAIN_NEW_TASK_LINK_SERVICE,
  OPEN_TARGET_LINK_SERVICE as MAIN_OPEN_TARGET_LINK_SERVICE,
  POSTHOG_PLUGIN_SERVICE as MAIN_POSTHOG_PLUGIN_SERVICE,
  PROCESS_TRACKING_SERVICE as MAIN_PROCESS_TRACKING_SERVICE,
  PROVISIONING_SERVICE as MAIN_PROVISIONING_SERVICE,
  REPOSITORY_REPOSITORY as MAIN_REPOSITORY_REPOSITORY,
  SCOUT_LINK_SERVICE as MAIN_SCOUT_LINK_SERVICE,
  SECURE_STORE_BACKEND as MAIN_SECURE_STORE_BACKEND,
  SECURE_STORE_SERVICE as MAIN_SECURE_STORE_SERVICE,
  SETTINGS_STORE as MAIN_SETTINGS_STORE,
  SLEEP_SERVICE as MAIN_SLEEP_SERVICE,
  SUSPENSION_REPOSITORY as MAIN_SUSPENSION_REPOSITORY,
  SUSPENSION_SERVICE as MAIN_SUSPENSION_SERVICE,
  TASK_LINK_SERVICE as MAIN_TASK_LINK_SERVICE,
  UPDATES_SERVICE as MAIN_UPDATES_SERVICE,
  WATCHER_REGISTRY_SERVICE as MAIN_WATCHER_REGISTRY_SERVICE,
  WORKSPACE_CLIENT as MAIN_WORKSPACE_CLIENT,
  WORKSPACE_REPOSITORY as MAIN_WORKSPACE_REPOSITORY,
  WORKSPACE_SERVER_SERVICE as MAIN_WORKSPACE_SERVER_SERVICE,
  WORKSPACE_SERVICE as MAIN_WORKSPACE_SERVICE,
  WORKTREE_REPOSITORY as MAIN_WORKTREE_REPOSITORY,
} from "./tokens";

async function cancelTaskSessions(
  agentService: AgentService,
  piSessionService: PiSessionService,
  taskId: string,
): Promise<void> {
  await Promise.all([
    agentService.cancelSessionsByTaskId(taskId),
    piSessionService.stop(taskId),
  ]);
}

export const container = new TypedContainer<MainBindings>({
  defaultScope: "Singleton",
});

container.bind(URL_LAUNCHER_SERVICE).to(ElectronUrlLauncher);
container.bind(STORAGE_PATHS_SERVICE).to(ElectronStoragePaths);
container.bind(APP_META_SERVICE).to(ElectronAppMeta);
container.bind(DIALOG_SERVICE).to(ElectronDialog);
container.bind(CLIPBOARD_SERVICE).to(ElectronClipboard);
container.bind(CRYPTO_SERVICE).to(ElectronCrypto);
container.bind(ANALYTICS_SERVICE).toConstantValue(posthogNodeAnalytics);
container.bind(FILE_ICON_SERVICE).to(ElectronFileIcon);
container.bind(SECURE_STORAGE_SERVICE).to(ElectronSecureStorage);
container.bind(MAIN_WINDOW_SERVICE).to(ElectronMainWindow);
container.bind(APP_LIFECYCLE_SERVICE).to(ElectronAppLifecycle);
container.bind(POWER_MANAGER_SERVICE).to(ElectronPowerManager);
container.bind(UPDATER_SERVICE).to(ElectronUpdater);
container.bind(NOTIFIER_SERVICE).to(ElectronNotifier);
container.bind(CONTEXT_MENU_SERVICE).to(ElectronContextMenu);
container.bind(BUNDLED_RESOURCES_SERVICE).to(ElectronBundledResources);
container.bind(IMAGE_PROCESSOR_SERVICE).to(ElectronImageProcessor);
container.bind(WORKSPACE_SETTINGS_SERVICE).to(ElectronWorkspaceSettings);
container.bind(APP_METRICS_SERVICE).to(ElectronAppMetrics);
container.bind(DEV_HOST_ACTIONS_SERVICE).to(ElectronDevHostActions);

container.load(databaseModule);
container.load(repositoriesModule);
container.bind(MAIN_DATABASE_SERVICE).toService(DATABASE_SERVICE);
container
  .bind(MAIN_AUTH_PREFERENCE_REPOSITORY)
  .toService(AUTH_PREFERENCE_REPOSITORY);
container.bind(MAIN_AUTH_SESSION_REPOSITORY).toService(AUTH_SESSION_REPOSITORY);
container.bind(MAIN_REPOSITORY_REPOSITORY).toService(REPOSITORY_REPOSITORY);
container.bind(MAIN_WORKSPACE_REPOSITORY).toService(WORKSPACE_REPOSITORY);
container.bind(MAIN_WORKTREE_REPOSITORY).toService(WORKTREE_REPOSITORY);
container.bind(MAIN_ARCHIVE_REPOSITORY).toService(ARCHIVE_REPOSITORY);
container.bind(MAIN_SUSPENSION_REPOSITORY).toService(SUSPENSION_REPOSITORY);
container
  .bind(MAIN_DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY)
  .toService(DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY);
container.load(agentModule);
container.bind(PI_RUNTIME_FACTORY).to(DesktopPiRuntimeFactory);
container.load(piSessionModule);
container.bind(AGENT_SLEEP_COORDINATOR).toService(MAIN_SLEEP_SERVICE);
container.bind(AGENT_MCP_APPS).toService(MCP_APPS_SERVICE);
container.bind(AGENT_REPO_FILES).toService(MAIN_FS_SERVICE);
container.bind(AGENT_AUTH).toService(MAIN_AUTH_SERVICE);
container
  .bind(PI_RPC_CLIENT_FACTORY)
  .to(DesktopPiRpcClientFactory)
  .inSingletonScope();
container.bind(AGENT_LOGGER).toConstantValue(logger);
container.load(osModule);
container.bind<RootLogger>(ROOT_LOGGER).toConstantValue(logger);
container.bind(AUTH_SESSION_STORE).to(AuthSessionPortAdapter);
container.bind(AUTH_PREFERENCE_STORE).to(AuthPreferencePortAdapter);
container.bind(AUTH_OAUTH_FLOW_SERVICE).to(OAuthFlowPortAdapter);
container.bind(AUTH_TOKEN_CIPHER).to(TokenCipherPortAdapter);
container.bind(AUTH_CONNECTIVITY).to(ConnectivityPortAdapter);
container
  .bind(AUTH_TOKEN_OVERRIDE)
  .toConstantValue(process.env.VITE_POSTHOG_ACCESS_TOKEN_OVERRIDE ?? null);
container.bind(MAIN_AUTH_SERVICE).to(AuthService);
container.bind(AUTH_SERVICE).toService(MAIN_AUTH_SERVICE);
container.load(authProxyModule);
container.bind(AUTH_PROXY_AUTH).toDynamicValue((ctx) => ({
  authenticatedFetch: (url: string, init?: RequestInit) =>
    ctx
      .get<AuthService>(MAIN_AUTH_SERVICE)
      .authenticatedFetch(fetch, url, init),
}));
container.load(mcpProxyModule);
container.bind(MCP_PROXY_AUTH).toDynamicValue((ctx) => {
  const auth = () => ctx.get<AuthService>(MAIN_AUTH_SERVICE);
  return {
    authenticatedFetch: (url: string, init?: RequestInit) =>
      auth().authenticatedFetch(fetch, url, init),
    refreshAccessToken: () => auth().refreshAccessToken(),
  };
});
container.load(archiveModule);
container.bind(ARCHIVE_SESSION_CANCELLER).toDynamicValue((ctx) => ({
  cancelSessionsByTaskId: (taskId: string) =>
    cancelTaskSessions(
      ctx.get<AgentService>(AGENT_SERVICE),
      ctx.get<PiSessionService>(PI_SESSION_SERVICE),
      taskId,
    ),
}));
container.bind(ARCHIVE_FILE_WATCHER).toDynamicValue((ctx) => ({
  stopWatching: async (worktreePath: string) => {
    ctx
      .get<FileWatcherBridge>(MAIN_FILE_WATCHER_SERVICE)
      .stopWatching(worktreePath);
  },
}));
container.load(suspensionModule);
container.bind(SUSPENSION_SESSION_CANCELLER).toDynamicValue((ctx) => ({
  cancelSessionsByTaskId: (taskId: string) =>
    cancelTaskSessions(
      ctx.get<AgentService>(AGENT_SERVICE),
      ctx.get<PiSessionService>(PI_SESSION_SERVICE),
      taskId,
    ),
}));
container.bind(SUSPENSION_FILE_WATCHER).toDynamicValue((ctx) => ({
  stopWatching: async (worktreePath: string) => {
    ctx
      .get<FileWatcherBridge>(MAIN_FILE_WATCHER_SERVICE)
      .stopWatching(worktreePath);
  },
}));
container.bind(MAIN_SUSPENSION_SERVICE).toService(SUSPENSION_SERVICE);
container.bind(MAIN_APP_LIFECYCLE_SERVICE).to(AppLifecycleService);
container.load(cloudTaskModule);
container.bind(CLOUD_TASK_AUTH).toDynamicValue((ctx) => ({
  authenticatedFetch: (url: string, init?: RequestInit) =>
    ctx
      .get<AuthService>(MAIN_AUTH_SERVICE)
      .authenticatedFetch(fetch, url, init),
  getCloudContext: async () => {
    const auth = ctx.get<AuthService>(MAIN_AUTH_SERVICE);
    const { apiHost } = await auth.getValidAccessToken();
    const teamId = auth.getState().currentProjectId;
    return teamId === null ? null : { apiHost, teamId };
  },
}));
container.bind(MAIN_CLOUD_TASK_SERVICE).toService(CLOUD_TASK_SERVICE);
container.load(contextMenuCoreModule);
container
  .bind(CONTEXT_MENU_EXTERNAL_APPS_SERVICE)
  .toService(MAIN_EXTERNAL_APPS_SERVICE);
container.bind(MAIN_CONTEXT_MENU_SERVICE).toService(CONTEXT_MENU_CONTROLLER);
container.bind(MAIN_DEEP_LINK_SERVICE).to(DeepLinkService);
container.bind(DEEP_LINK_SERVICE).toService(MAIN_DEEP_LINK_SERVICE);
container.load(enrichmentModule);
container.bind(ENRICHMENT_AUTH).toDynamicValue((ctx) => {
  const auth = () => ctx.get<AuthService>(MAIN_AUTH_SERVICE);
  return {
    getState: () => {
      const state = auth().getState();
      return {
        status: state.status,
        projectId: state.currentProjectId ?? null,
        cloudRegion: state.cloudRegion ?? null,
      };
    },
    getValidAccessToken: async () => {
      const token = await auth().getValidAccessToken();
      return { accessToken: token.accessToken, apiHost: token.apiHost };
    },
  };
});
container.bind(ENRICHMENT_FILE_READER).toConstantValue({
  stat: (p: string) => fsStat(p).then((s) => ({ size: s.size })),
  readFile: (p: string) => fsReadFile(p, "utf-8"),
  listFilesContainingText: (repoPath: string, text: string) =>
    listFilesContainingText(repoPath, text),
});
container.bind(MAIN_PROVISIONING_SERVICE).to(ProvisioningService);
container.bind(PROVISIONING_SERVICE).toService(MAIN_PROVISIONING_SERVICE);

const externalAppsPrefsStore = new ExternalAppsStoreImpl<{
  externalAppsPrefs: ExternalAppsPreferences;
}>({
  name: "external-apps",
  cwd: getUserDataDir(),
  defaults: { externalAppsPrefs: {} },
});
container.bind(EXTERNAL_APPS_STORE).toConstantValue({
  getPrefs: () => externalAppsPrefsStore.get("externalAppsPrefs"),
  setPrefs: (prefs: ExternalAppsPreferences) =>
    externalAppsPrefsStore.set("externalAppsPrefs", prefs),
});
container.load(externalAppsModule);
container.bind(MAIN_EXTERNAL_APPS_SERVICE).toService(EXTERNAL_APPS_SERVICE);
container.load(llmGatewayModule);
container.bind(LLM_GATEWAY_HOST).toDynamicValue((ctx) => {
  const auth = () => ctx.get<AuthService>(MAIN_AUTH_SERVICE);
  return {
    getValidAccessToken: () => auth().getValidAccessToken(),
    authenticatedFetch: (url: string, init?: RequestInit) =>
      auth().authenticatedFetch(fetch, url, init),
    messagesUrl: (apiHost: string) =>
      `${getLlmGatewayUrl(apiHost)}/v1/messages`,
    usageUrl: (apiHost: string) => getGatewayUsageUrl(apiHost),
    defaultModel: DEFAULT_GATEWAY_MODEL,
  };
});
container.bind(MAIN_LLM_GATEWAY_SERVICE).toService(LLM_GATEWAY_SERVICE);
container.load(mcpAppsModule);
container.bind(MAIN_MCP_APPS_SERVICE).toService(MCP_APPS_SERVICE);
container.load(foldersModule);
container.load(integrationsModule);
container.load(gitPrModule);
container.bind(GIT_DIFF_SOURCE).toDynamicValue((ctx) => {
  const wsClient = () => ctx.get<HostGitWorkspaceClient>(GIT_WORKSPACE_CLIENT);
  const git = () => wsClient().git;
  return {
    getStagedDiff: (directoryPath: string) =>
      git().getDiffCached.query({ directoryPath }),
    getUnstagedDiff: (directoryPath: string) =>
      git().getDiffUnstaged.query({ directoryPath }),
    getCommitConventions: (directoryPath: string) =>
      git().getCommitConventions.query({ directoryPath }),
    getChangedFilesHead: (directoryPath: string) =>
      git().getChangedFilesHead.query({ directoryPath }),
    getDefaultBranch: (directoryPath: string) =>
      git().getDefaultBranch.query({ directoryPath }),
    getCurrentBranch: (directoryPath: string) =>
      git().getCurrentBranch.query({ directoryPath }),
    getDiffAgainstRemote: (directoryPath: string, baseBranch: string) =>
      git().getDiffAgainstRemote.query({ directoryPath, baseBranch }),
    getCommitsBetweenBranches: (
      directoryPath: string,
      baseBranch: string,
      head: string | undefined,
      limit: number,
    ) =>
      git().getCommitsBetweenBranches.query({
        directoryPath,
        baseBranch,
        head,
        limit,
      }),
    getPrTemplate: (directoryPath: string) =>
      git().getPrTemplate.query({ directoryPath }),
    fetchFromRemote: async (directoryPath: string) => {
      await git().getGitSyncStatus.query({
        directoryPath,
        fetchFromRemote: true,
      });
    },
  };
});
container
  .bind(GIT_AGENT_SERVICE)
  .toDynamicValue((ctx) => ctx.get<AgentService>(AGENT_SERVICE));
container
  .bind<GitWorkspaceLookup>(GIT_WORKSPACE_LOOKUP)
  .toDynamicValue((ctx): GitWorkspaceLookup => {
    const workspace = () => ctx.get<WorkspaceService>(WORKSPACE_SERVICE);
    return {
      getWorkspace: (taskId) => workspace().getWorkspace(taskId),
      linkBranch: (taskId, branch, source) =>
        workspace().linkBranch(taskId, branch, source),
    };
  });
container.load(gitHostModule);
container.bind(WS_GIT_SERVICE).to(GitService).inSingletonScope();
container
  .bind<IGitPrStatus>(GIT_PR_STATUS_PROVIDER)
  .to(TaskPrStatusService)
  .inSingletonScope();
container.load(handoffModule);
container.bind(HANDOFF_HOST).to(HandoffHostService).inSingletonScope();
container.bind(HANDOFF_GIT_GATEWAY).toDynamicValue((ctx): HandoffGitGateway => {
  const workspace = ctx.get<WorkspaceClient>(MAIN_WORKSPACE_CLIENT);
  return {
    async getChangedFiles(repoPath) {
      const files = await workspace.git.getChangedFilesHead.query({
        directoryPath: repoPath,
      });
      return files.map((f) => ({
        path: f.path,
        status: f.status,
        linesAdded: f.linesAdded,
        linesRemoved: f.linesRemoved,
      }));
    },
    getLocalGitState: (repoPath) =>
      workspace.git.readHandoffLocalGitState.query({
        directoryPath: repoPath,
      }),
    cleanupAfterCloudHandoff: (repoPath, branchName) =>
      workspace.git.cleanupAfterCloudHandoff.mutate({
        directoryPath: repoPath,
        branchName,
      }),
  };
});
container.bind(HANDOFF_LOG_GATEWAY).toDynamicValue((ctx) => {
  const ws = ctx.get<WorkspaceClient>(MAIN_WORKSPACE_CLIENT);
  return {
    seedLocalLogs: (taskRunId: string, content: string) =>
      ws.localLogs.seed.mutate({ taskRunId, content }),
    countLocalLogEntries: (taskRunId: string) =>
      ws.localLogs.count.query({ taskRunId }),
    deleteLocalLogCache: (taskRunId: string) =>
      ws.localLogs.delete.mutate({ taskRunId }),
  };
});
container.load(mcpCallbackModule);
container.bind(NOTIFICATION_SERVICE).to(NotificationService);
container.load(oauthCallbackModule);
container.load(oauthModule);
container
  .bind(OAUTH_HOST)
  .toDynamicValue((ctx) => {
    const callback = ctx.get<OAuthCallbackReceiver>(OAUTH_CALLBACK_SERVER);
    return {
      waitForCode: callback.waitForCode.bind(callback),
      isDev: isDevBuild(),
    };
  })
  .inSingletonScope();
container.load(processTrackingModule);
container.load(workspaceMetadataModule);
container
  .bind(MAIN_PROCESS_TRACKING_SERVICE)
  .toService(PROCESS_TRACKING_SERVICE);
container.load(posthogPluginModule);
container.bind(MAIN_POSTHOG_PLUGIN_SERVICE).toService(POSTHOG_PLUGIN_SERVICE);
container.load(skillsModule);
container.load(skillsMarketplaceModule);
container.load(releaseFeedModule);
container.load(onboardingImportModule);
container.load(localMcpModule);
container.load(mcpRelayModule);
// Core's cloud-task service executes MCP relay requests through this seam;
// the workspace relay service satisfies the core executor interface
// structurally (docs/cloud-mcp-relay.md).
container
  .bind(MCP_RELAY_EXECUTOR)
  .toDynamicValue((ctx) => ctx.get(MCP_RELAY_SERVICE))
  .inSingletonScope();
container.load(claudeCliSessionsModule);
container.load(additionalDirectoriesModule);
container.bind(MAIN_SLEEP_SERVICE).to(SleepService);
container.bind(SLEEP_SERVICE).toService(MAIN_SLEEP_SERVICE);
container.load(shellModule);
container.load(uiModule);
container.bind(UI_AUTH).toDynamicValue((ctx) => ({
  invalidateAccessTokenForTest: () =>
    ctx.get<AuthService>(MAIN_AUTH_SERVICE).invalidateAccessTokenForTest(),
}));
container.load(updatesCoreModule);
container.bind(UPDATE_LIFECYCLE_SERVICE).toService(MAIN_APP_LIFECYCLE_SERVICE);
container.bind(MAIN_UPDATES_SERVICE).toService(UPDATES_SERVICE);
container.load(usageMonitorModule);
container.bind(USAGE_HOST).toDynamicValue((ctx) => {
  const agent = () => ctx.get<AgentService>(AGENT_SERVICE);
  return {
    fetchUsage: () =>
      ctx.get<LlmGatewayService>(MAIN_LLM_GATEWAY_SERVICE).fetchUsage(),
    onLlmActivity: (listener: () => void) =>
      agent().on(AgentServiceEvent.LlmActivity, listener),
    offLlmActivity: (listener: () => void) =>
      agent().off(AgentServiceEvent.LlmActivity, listener),
    hasActiveSessions: () => agent().hasActiveSessions(),
    getThresholdsSeen: () => electronUsageThresholdStore.getThresholdsSeen(),
    setThresholdsSeen: (value: Record<string, string>) =>
      electronUsageThresholdStore.setThresholdsSeen(value),
  };
});
container.bind(MAIN_TASK_LINK_SERVICE).to(TaskLinkService);
container.bind(TASK_LINK_SERVICE).toService(MAIN_TASK_LINK_SERVICE);
container.bind(MAIN_INBOX_LINK_SERVICE).to(InboxLinkService);
container.bind(INBOX_LINK_SERVICE).toService(MAIN_INBOX_LINK_SERVICE);
container.bind(MAIN_SCOUT_LINK_SERVICE).to(ScoutLinkService);
container.bind(SCOUT_LINK_SERVICE).toService(MAIN_SCOUT_LINK_SERVICE);
container.bind(MAIN_NEW_TASK_LINK_SERVICE).to(NewTaskLinkService);
container.bind(NEW_TASK_LINK_SERVICE).toService(MAIN_NEW_TASK_LINK_SERVICE);
container.bind(MAIN_APPROVAL_LINK_SERVICE).to(ApprovalLinkService);
container.bind(APPROVAL_LINK_SERVICE).toService(MAIN_APPROVAL_LINK_SERVICE);
container.bind(MAIN_OPEN_TARGET_LINK_SERVICE).to(OpenTargetLinkService);
container
  .bind(OPEN_TARGET_LINK_SERVICE)
  .toService(MAIN_OPEN_TARGET_LINK_SERVICE);
container.bind(MAIN_CANVAS_LINK_SERVICE).to(CanvasLinkService);
container.bind(CANVAS_LINK_SERVICE).toService(MAIN_CANVAS_LINK_SERVICE);
container.bind(MAIN_CHANNEL_LINK_SERVICE).to(ChannelLinkService);
container.bind(CHANNEL_LINK_SERVICE).toService(MAIN_CHANNEL_LINK_SERVICE);
container.load(watcherRegistryModule);
container
  .bind(MAIN_WATCHER_REGISTRY_SERVICE)
  .toService(WATCHER_REGISTRY_SERVICE);
container.load(workspaceModule);
container.bind(WORKSPACE_AGENT).toDynamicValue((ctx): WorkspaceAgent => {
  const agent = ctx.get<AgentService>(AGENT_SERVICE);
  return {
    cancelSessionsByTaskId: (taskId) =>
      cancelTaskSessions(
        agent,
        ctx.get<PiSessionService>(PI_SESSION_SERVICE),
        taskId,
      ),
    onAgentFileActivity: (handler) =>
      agent.on(AgentServiceEvent.AgentFileActivity, handler),
  };
});
container
  .bind(WORKSPACE_FILE_WATCHER)
  .toDynamicValue((ctx): WorkspaceFileWatcher => {
    const fileWatcher = ctx.get<FileWatcherBridge>(MAIN_FILE_WATCHER_SERVICE);
    return {
      stopWatching: async (worktreePath) => {
        fileWatcher.stopWatching(worktreePath);
      },
      onGitStateChanged: (handler) =>
        fileWatcher.on(FileWatcherEventKind.GitStateChanged, (event) =>
          handler({ repoPath: event.repoPath }),
        ),
    };
  });
container.bind(WORKSPACE_FOCUS).toDynamicValue((ctx): WorkspaceFocus => {
  const focus = ctx.get(FocusHostService);
  return {
    onBranchRenamed: (handler) =>
      focus.on(FocusServiceEvent.BranchRenamed, handler),
  };
});
container
  .bind(WORKSPACE_PROVISIONING)
  .toDynamicValue((ctx): WorkspaceProvisioning => {
    const provisioning = ctx.get<ProvisioningService>(
      MAIN_PROVISIONING_SERVICE,
    );
    return {
      emitOutput: (taskId, data) => provisioning.emitOutput(taskId, data),
    };
  });
container.bind(MAIN_WORKSPACE_SERVICE).toService(WORKSPACE_SERVICE);
container
  .bind(MAIN_WORKSPACE_SERVER_SERVICE)
  .to(WorkspaceServerService)
  .inSingletonScope();

container.bind(MAIN_SETTINGS_STORE).toConstantValue(settingsStore);

container.bind(MAIN_SECURE_STORE_BACKEND).toConstantValue(rendererStore);
container
  .bind(MAIN_SECURE_STORE_SERVICE)
  .to(SecureStoreService)
  .inSingletonScope();
container.bind(SECURE_STORE_SERVICE).toService(MAIN_SECURE_STORE_SERVICE);
container
  .bind(SPEECH_SYNTHESIZER_SERVICE)
  .to(ElevenLabsSpeechService)
  .inSingletonScope();
container.bind(LOGS_SERVICE).toDynamicValue((ctx) => {
  const ws = ctx.get<WorkspaceClient>(MAIN_WORKSPACE_CLIENT);
  return {
    fetchS3Logs: async (logUrl: string) => {
      try {
        const response = await fetch(logUrl);
        if (response.status === 404) return null;
        if (!response.ok) return null;
        return await response.text();
      } catch {
        return null;
      }
    },
    readLocalLogs: (taskRunId: string) =>
      ws.localLogs.read.query({ taskRunId }),
    readLocalLogsCollapsed: (taskRunId: string) =>
      ws.localLogs.readCollapsed.query({ taskRunId }),
    readLocalLogsTail: (taskRunId: string, maxBytes: number) =>
      ws.localLogs.readTail.query({ taskRunId, maxBytes }),
    writeLocalLogs: (taskRunId: string, content: string) =>
      ws.localLogs.write.mutate({ taskRunId, content }),
  };
});
container.bind(MAIN_ENCRYPTION_SERVICE).to(EncryptionService);
container.bind(MAIN_DISCORD_PRESENCE_SERVICE).to(DiscordPresenceService);

// Canvas / dashboards (project-bluebird). The host-agnostic dashboard services
// live in @posthog/core (bound via canvasCoreModule) and resolve through
// ctx.container in the host-router routers.
container.load(canvasCoreModule);

// Browser tabs for the Channels canvas surface. Authoritative sqlite-backed
// service in the main process; resolved by the host-router browserTabs router.
container.load(browserTabsModule);

container.bind(MAIN_DEV_FLAGS_SERVICE).to(DevFlagsService);
container.bind(MAIN_DEV_METRICS_SERVICE).to(DevMetricsService);
container.bind(MAIN_DEV_NETWORK_SERVICE).to(DevNetworkService);
container.bind(MAIN_DEV_LOGS_SERVICE).to(DevLogsService);
container.bind(MAIN_DEV_ACTIONS_SERVICE).to(DevActionsService);

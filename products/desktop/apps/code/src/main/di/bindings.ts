import type { AuthService } from "@posthog/core/auth/auth";
import type { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import type {
  AUTH_CONNECTIVITY,
  AUTH_OAUTH_FLOW_SERVICE,
  AUTH_PREFERENCE_STORE,
  AUTH_SESSION_STORE,
  AUTH_TOKEN_CIPHER,
  AUTH_TOKEN_OVERRIDE,
} from "@posthog/core/auth/identifiers";
import type {
  CLOUD_TASK_AUTH,
  ICloudTaskAuth,
  MCP_RELAY_EXECUTOR,
  McpRelayExecutor,
} from "@posthog/core/cloud-task/identifiers";
import type {
  CONTEXT_MENU_EXTERNAL_APPS_SERVICE,
  IContextMenuExternalApps,
} from "@posthog/core/context-menu/identifiers";
import type {
  FOCUS_SESSION_STORE,
  FOCUS_WORKSPACE_CLIENT,
  FOCUS_WORKTREE_PATHS,
  FocusSessionStore,
  FocusWorkspaceClient,
  FocusWorktreePaths,
} from "@posthog/core/focus/host-focus";
import type {
  GitWorkspaceLookup,
  HostGitWorkspaceClient,
} from "@posthog/core/git/host-git";
import type {
  GIT_AGENT_SERVICE,
  GIT_WORKSPACE_CLIENT,
  GIT_WORKSPACE_LOOKUP,
} from "@posthog/core/git/identifiers";
import type {
  GIT_DIFF_SOURCE,
  GitDiffSource,
} from "@posthog/core/git-pr/identifiers";
import type { HANDOFF_HOST } from "@posthog/core/handoff/identifiers";
import type { GitHubIntegrationService } from "@posthog/core/integrations/github";
import type {
  GITHUB_INTEGRATION_SERVICE,
  SLACK_INTEGRATION_SERVICE,
} from "@posthog/core/integrations/identifiers";
import type { SlackIntegrationService } from "@posthog/core/integrations/slack";
import type { ApprovalLinkService } from "@posthog/core/links/approval-link";
import type { CanvasLinkService } from "@posthog/core/links/canvas-link";
import type { ChannelLinkService } from "@posthog/core/links/channel-link";
import type {
  APPROVAL_LINK_SERVICE,
  CANVAS_LINK_SERVICE,
  CHANNEL_LINK_SERVICE,
  INBOX_LINK_SERVICE,
  NEW_TASK_LINK_SERVICE,
  OPEN_TARGET_LINK_SERVICE,
  SCOUT_LINK_SERVICE,
  TASK_LINK_SERVICE,
} from "@posthog/core/links/identifiers";
import type { InboxLinkService } from "@posthog/core/links/inbox-link";
import type { NewTaskLinkService } from "@posthog/core/links/new-task-link";
import type { OpenTargetLinkService } from "@posthog/core/links/open-target-link";
import type { ScoutLinkService } from "@posthog/core/links/scout-link";
import type { TaskLinkService } from "@posthog/core/links/task-link";
import type {
  LLM_GATEWAY_HOST,
  LlmGatewayHost,
} from "@posthog/core/llm-gateway/identifiers";
import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import type { MCP_APPS_SERVICE } from "@posthog/core/mcp-apps/identifiers";
import type { McpAppsService } from "@posthog/core/mcp-apps/mcp-apps";
import type { NOTIFICATION_SERVICE } from "@posthog/core/notification/identifiers";
import type { NotificationService } from "@posthog/core/notification/notification";
import type {
  OAUTH_HOST,
  OAUTH_SERVICE,
  OAuthHost,
} from "@posthog/core/oauth/identifiers";
import type { OAuthService } from "@posthog/core/oauth/oauth";
import type { PROVISIONING_SERVICE } from "@posthog/core/provisioning/identifiers";
import type { ProvisioningService } from "@posthog/core/provisioning/provisioning";
import type { SLEEP_SERVICE } from "@posthog/core/sleep/identifiers";
import type { SleepService } from "@posthog/core/sleep/sleep";
import type { UI_AUTH, UI_SERVICE } from "@posthog/core/ui/identifiers";
import type { UIService } from "@posthog/core/ui/ui";
import type { UPDATE_LIFECYCLE_SERVICE } from "@posthog/core/updates/identifiers";
import type { UpdatesService } from "@posthog/core/updates/updates";
import type { USAGE_HOST, UsageHost } from "@posthog/core/usage/identifiers";
import type { ROOT_LOGGER, RootLogger } from "@posthog/di/logger";
import type {
  CONNECTIVITY_CLIENT,
  HostConnectivityClient,
} from "@posthog/host-router/ports/connectivity-client";
import type {
  ENVIRONMENT_CLIENT,
  HostEnvironmentClient,
} from "@posthog/host-router/ports/environment-client";
import type {
  FILE_WATCHER_CONTROL,
  HostFileWatcherControl,
} from "@posthog/host-router/ports/file-watcher-control";
import type {
  GIT_PR_STATUS_PROVIDER,
  IGitPrStatus,
} from "@posthog/host-router/ports/git-pr-status";
import type {
  ANALYTICS_SERVICE,
  IAnalytics,
} from "@posthog/platform/analytics";
import type { APP_LIFECYCLE_SERVICE } from "@posthog/platform/app-lifecycle";
import type { APP_META_SERVICE } from "@posthog/platform/app-meta";
import type { APP_METRICS_SERVICE } from "@posthog/platform/app-metrics";
import type { BUNDLED_RESOURCES_SERVICE } from "@posthog/platform/bundled-resources";
import type { CLIPBOARD_SERVICE } from "@posthog/platform/clipboard";
import type { CONTEXT_MENU_SERVICE } from "@posthog/platform/context-menu";
import type { CRYPTO_SERVICE } from "@posthog/platform/crypto";
import type { DEEP_LINK_SERVICE } from "@posthog/platform/deep-link";
import type { DEV_HOST_ACTIONS_SERVICE } from "@posthog/platform/dev-host-actions";
import type { DIALOG_SERVICE } from "@posthog/platform/dialog";
import type { FILE_ICON_SERVICE } from "@posthog/platform/file-icon";
import type { IMAGE_PROCESSOR_SERVICE } from "@posthog/platform/image-processor";
import type { MAIN_WINDOW_SERVICE } from "@posthog/platform/main-window";
import type { NOTIFIER_SERVICE } from "@posthog/platform/notifier";
import type { POWER_MANAGER_SERVICE } from "@posthog/platform/power-manager";
import type { SECURE_STORAGE_SERVICE } from "@posthog/platform/secure-storage";
import type { STORAGE_PATHS_SERVICE } from "@posthog/platform/storage-paths";
import type { UPDATER_SERVICE } from "@posthog/platform/updater";
import type { URL_LAUNCHER_SERVICE } from "@posthog/platform/url-launcher";
import type { WORKSPACE_SETTINGS_SERVICE } from "@posthog/platform/workspace-settings";
import type { WorkspaceClient } from "@posthog/workspace-client/client";
import type { DatabaseService } from "@posthog/workspace-server/db/service";
import type { GIT_SERVICE as WS_GIT_SERVICE } from "@posthog/workspace-server/di/tokens";
import type { AgentService } from "@posthog/workspace-server/services/agent/agent";
import type {
  AGENT_AUTH,
  AGENT_LOGGER,
  AGENT_MCP_APPS,
  AGENT_REPO_FILES,
  AGENT_SERVICE,
  AGENT_SLEEP_COORDINATOR,
} from "@posthog/workspace-server/services/agent/identifiers";
import type {
  ARCHIVE_FILE_WATCHER,
  ARCHIVE_SESSION_CANCELLER,
} from "@posthog/workspace-server/services/archive/identifiers";
import type {
  ArchiveFileWatcher,
  SessionCanceller,
} from "@posthog/workspace-server/services/archive/ports";
import type { AUTH_PROXY_AUTH } from "@posthog/workspace-server/services/auth-proxy/identifiers";
import type { AuthProxyAuth } from "@posthog/workspace-server/services/auth-proxy/ports";
import type {
  ENRICHMENT_AUTH,
  ENRICHMENT_FILE_READER,
} from "@posthog/workspace-server/services/enrichment/identifiers";
import type {
  EnrichmentAuth,
  EnrichmentFileReader,
} from "@posthog/workspace-server/services/enrichment/ports";
import type { ExternalAppsService } from "@posthog/workspace-server/services/external-apps/external-apps";
import type { EXTERNAL_APPS_STORE } from "@posthog/workspace-server/services/external-apps/identifiers";
import type { ExternalAppsStore } from "@posthog/workspace-server/services/external-apps/ports";
import type {
  FS_SERVICE,
  FsCapability,
} from "@posthog/workspace-server/services/fs/identifiers";
import type { GitService } from "@posthog/workspace-server/services/git/service";
import type {
  HANDOFF_GIT_GATEWAY,
  HANDOFF_LOG_GATEWAY,
} from "@posthog/workspace-server/services/handoff/identifiers";
import type {
  HandoffGitGateway,
  HandoffLogGateway,
} from "@posthog/workspace-server/services/handoff/ports";
import type { HandoffHostService } from "@posthog/workspace-server/services/handoff/service";
import type {
  ILogsService,
  LOGS_SERVICE,
} from "@posthog/workspace-server/services/local-logs/identifiers";
import type { MCP_PROXY_AUTH } from "@posthog/workspace-server/services/mcp-proxy/identifiers";
import type { McpProxyAuth } from "@posthog/workspace-server/services/mcp-proxy/ports";
import type {
  MCP_RELAY_SERVICE,
  McpRelayService,
} from "@posthog/workspace-server/services/mcp-relay/identifiers";
import type {
  PI_RPC_CLIENT_FACTORY,
  PI_RUNTIME_FACTORY,
  PiRpcClientFactory,
  PiRuntimeFactory,
} from "@posthog/workspace-server/services/pi-session/identifiers";
import type { PosthogPluginService } from "@posthog/workspace-server/services/posthog-plugin/posthog-plugin";
import type { ProcessTrackingService } from "@posthog/workspace-server/services/process-tracking/process-tracking";
import type {
  ISecureStoreService,
  SECURE_STORE_SERVICE,
} from "@posthog/workspace-server/services/secure-store/identifiers";
import type {
  ISpeechSynthesizer,
  SPEECH_SYNTHESIZER_SERVICE,
} from "@posthog/workspace-server/services/speech/identifiers";
import type {
  SUSPENSION_FILE_WATCHER,
  SUSPENSION_SERVICE,
  SUSPENSION_SESSION_CANCELLER,
} from "@posthog/workspace-server/services/suspension/identifiers";
import type {
  SuspensionFileWatcher,
  SessionCanceller as SuspensionSessionCanceller,
} from "@posthog/workspace-server/services/suspension/ports";
import type { SuspensionService } from "@posthog/workspace-server/services/suspension/suspension";
import type { WatcherRegistryService } from "@posthog/workspace-server/services/watcher-registry/watcher-registry";
import type {
  WORKSPACE_AGENT,
  WORKSPACE_FILE_WATCHER,
  WORKSPACE_FOCUS,
  WORKSPACE_PROVISIONING,
} from "@posthog/workspace-server/services/workspace/identifiers";
import type {
  WorkspaceAgent,
  WorkspaceFileWatcher,
  WorkspaceFocus,
  WorkspaceProvisioning,
} from "@posthog/workspace-server/services/workspace/ports";
import type { WorkspaceService } from "@posthog/workspace-server/services/workspace/workspace";
import type { FileWatcherBridge } from "../index";
import type { ElectronAppLifecycle } from "../platform-adapters/electron-app-lifecycle";
import type { ElectronAppMeta } from "../platform-adapters/electron-app-meta";
import type { ElectronAppMetrics } from "../platform-adapters/electron-app-metrics";
import type { ElectronBundledResources } from "../platform-adapters/electron-bundled-resources";
import type { ElectronClipboard } from "../platform-adapters/electron-clipboard";
import type { ElectronContextMenu } from "../platform-adapters/electron-context-menu";
import type { ElectronCrypto } from "../platform-adapters/electron-crypto";
import type { ElectronDevHostActions } from "../platform-adapters/electron-dev-host-actions";
import type { ElectronDialog } from "../platform-adapters/electron-dialog";
import type { ElectronFileIcon } from "../platform-adapters/electron-file-icon";
import type { ElectronImageProcessor } from "../platform-adapters/electron-image-processor";
import type { ElectronMainWindow } from "../platform-adapters/electron-main-window";
import type { ElectronNotifier } from "../platform-adapters/electron-notifier";
import type { ElectronPowerManager } from "../platform-adapters/electron-power-manager";
import type { ElectronSecureStorage } from "../platform-adapters/electron-secure-storage";
import type { ElectronStoragePaths } from "../platform-adapters/electron-storage-paths";
import type { ElectronUpdater } from "../platform-adapters/electron-updater";
import type { ElectronUrlLauncher } from "../platform-adapters/electron-url-launcher";
import type { ElectronWorkspaceSettings } from "../platform-adapters/electron-workspace-settings";
import type { AppLifecycleService } from "../services/app-lifecycle/service";
import type {
  AuthPreferencePortAdapter,
  AuthSessionPortAdapter,
  ConnectivityPortAdapter,
  OAuthFlowPortAdapter,
  TokenCipherPortAdapter,
} from "../services/auth/port-adapters";
import type { DeepLinkService } from "../services/deep-link/service";
import type { DevActionsService } from "../services/dev-actions/service";
import type { DevFlagsService } from "../services/dev-flags/service";
import type { DevLogsService } from "../services/dev-logs/service";
import type { DevMetricsService } from "../services/dev-metrics/service";
import type { DevNetworkService } from "../services/dev-network/service";
import type { DiscordPresenceService } from "../services/discord-presence/service";
import type { EncryptionService } from "../services/encryption/service";
import type { SecureStoreService } from "../services/secure-store/service";
import type { settingsStore } from "../services/settingsStore";
import type { WorkspaceServerService } from "../services/workspace-server/service";
import type { rendererStore } from "../utils/store";
import type {
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

export interface MainBindings {
  // Platform adapters
  [URL_LAUNCHER_SERVICE]: ElectronUrlLauncher;
  [STORAGE_PATHS_SERVICE]: ElectronStoragePaths;
  [APP_META_SERVICE]: ElectronAppMeta;
  [DIALOG_SERVICE]: ElectronDialog;
  [CLIPBOARD_SERVICE]: ElectronClipboard;
  [CRYPTO_SERVICE]: ElectronCrypto;
  [ANALYTICS_SERVICE]: IAnalytics;
  [FILE_ICON_SERVICE]: ElectronFileIcon;
  [SECURE_STORAGE_SERVICE]: ElectronSecureStorage;
  [MAIN_WINDOW_SERVICE]: ElectronMainWindow;
  [APP_LIFECYCLE_SERVICE]: ElectronAppLifecycle;
  [POWER_MANAGER_SERVICE]: ElectronPowerManager;
  [UPDATER_SERVICE]: ElectronUpdater;
  [NOTIFIER_SERVICE]: ElectronNotifier;
  [CONTEXT_MENU_SERVICE]: ElectronContextMenu;
  [BUNDLED_RESOURCES_SERVICE]: ElectronBundledResources;
  [IMAGE_PROCESSOR_SERVICE]: ElectronImageProcessor;
  [WORKSPACE_SETTINGS_SERVICE]: ElectronWorkspaceSettings;
  [APP_METRICS_SERVICE]: ElectronAppMetrics;
  [DEV_HOST_ACTIONS_SERVICE]: ElectronDevHostActions;

  // Database (main aliases + ws-server source tokens via toService)
  [MAIN_DATABASE_SERVICE]: DatabaseService;
  [MAIN_AUTH_PREFERENCE_REPOSITORY]: unknown;
  [MAIN_AUTH_SESSION_REPOSITORY]: unknown;
  [MAIN_REPOSITORY_REPOSITORY]: unknown;
  [MAIN_WORKSPACE_REPOSITORY]: unknown;
  [MAIN_WORKTREE_REPOSITORY]: unknown;
  [MAIN_ARCHIVE_REPOSITORY]: unknown;
  [MAIN_SUSPENSION_REPOSITORY]: unknown;
  [MAIN_DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY]: unknown;

  // Agent host ports
  [AGENT_SLEEP_COORDINATOR]: unknown;
  [AGENT_MCP_APPS]: unknown;
  [AGENT_REPO_FILES]: unknown;
  [AGENT_AUTH]: unknown;
  [AGENT_LOGGER]: RootLogger;
  [PI_RPC_CLIENT_FACTORY]: PiRpcClientFactory;

  [PI_RUNTIME_FACTORY]: PiRuntimeFactory;

  // Logger
  [ROOT_LOGGER]: RootLogger;

  // Auth host ports
  [AUTH_SESSION_STORE]: AuthSessionPortAdapter;
  [AUTH_PREFERENCE_STORE]: AuthPreferencePortAdapter;
  [AUTH_OAUTH_FLOW_SERVICE]: OAuthFlowPortAdapter;
  [AUTH_TOKEN_CIPHER]: TokenCipherPortAdapter;
  [AUTH_CONNECTIVITY]: ConnectivityPortAdapter;
  [AUTH_TOKEN_OVERRIDE]: string | null;
  [MAIN_AUTH_SERVICE]: AuthService;
  [AUTH_SERVICE]: AuthService;

  // Auth proxy / mcp proxy / mcp relay
  [AUTH_PROXY_AUTH]: AuthProxyAuth;
  [MCP_PROXY_AUTH]: McpProxyAuth;
  [MCP_RELAY_SERVICE]: McpRelayService;
  [MCP_RELAY_EXECUTOR]: McpRelayExecutor;

  // Archive / suspension host ports
  [ARCHIVE_SESSION_CANCELLER]: SessionCanceller;
  [ARCHIVE_FILE_WATCHER]: ArchiveFileWatcher;
  [SUSPENSION_SESSION_CANCELLER]: SuspensionSessionCanceller;
  [SUSPENSION_FILE_WATCHER]: SuspensionFileWatcher;
  [MAIN_SUSPENSION_SERVICE]: SuspensionService;

  // Lifecycle / cloud task / context menu / deep link
  [MAIN_APP_LIFECYCLE_SERVICE]: AppLifecycleService;
  [CLOUD_TASK_AUTH]: ICloudTaskAuth;
  [MAIN_CLOUD_TASK_SERVICE]: unknown;
  [CONTEXT_MENU_EXTERNAL_APPS_SERVICE]: IContextMenuExternalApps;
  [MAIN_CONTEXT_MENU_SERVICE]: unknown;
  [MAIN_DEEP_LINK_SERVICE]: DeepLinkService;
  [DEEP_LINK_SERVICE]: DeepLinkService;

  // Enrichment host ports
  [ENRICHMENT_AUTH]: EnrichmentAuth;
  [ENRICHMENT_FILE_READER]: EnrichmentFileReader;

  // Provisioning
  [MAIN_PROVISIONING_SERVICE]: ProvisioningService;
  [PROVISIONING_SERVICE]: ProvisioningService;

  // External apps
  [EXTERNAL_APPS_STORE]: ExternalAppsStore;
  [MAIN_EXTERNAL_APPS_SERVICE]: ExternalAppsService;

  // Llm gateway
  [LLM_GATEWAY_HOST]: LlmGatewayHost;
  [MAIN_LLM_GATEWAY_SERVICE]: LlmGatewayService;

  // Mcp apps
  [MAIN_MCP_APPS_SERVICE]: McpAppsService;

  // Git
  [GIT_DIFF_SOURCE]: GitDiffSource;
  [GIT_AGENT_SERVICE]: unknown;
  [GIT_WORKSPACE_LOOKUP]: GitWorkspaceLookup;
  [GIT_PR_STATUS_PROVIDER]: IGitPrStatus;

  // Handoff
  [HANDOFF_HOST]: HandoffHostService;
  [HANDOFF_GIT_GATEWAY]: HandoffGitGateway;
  [HANDOFF_LOG_GATEWAY]: HandoffLogGateway;

  // Notification / oauth
  [NOTIFICATION_SERVICE]: NotificationService;
  [OAUTH_HOST]: OAuthHost;

  // Process tracking / posthog plugin
  [MAIN_PROCESS_TRACKING_SERVICE]: ProcessTrackingService;
  [MAIN_POSTHOG_PLUGIN_SERVICE]: PosthogPluginService;

  // Sleep
  [MAIN_SLEEP_SERVICE]: SleepService;
  [SLEEP_SERVICE]: SleepService;

  // Ui
  [UI_AUTH]: { invalidateAccessTokenForTest(): void };

  // Updates
  [UPDATE_LIFECYCLE_SERVICE]: AppLifecycleService;
  [MAIN_UPDATES_SERVICE]: UpdatesService;

  // Usage
  [USAGE_HOST]: UsageHost;

  // Links
  [MAIN_TASK_LINK_SERVICE]: TaskLinkService;
  [MAIN_INBOX_LINK_SERVICE]: InboxLinkService;
  [MAIN_SCOUT_LINK_SERVICE]: ScoutLinkService;
  [MAIN_NEW_TASK_LINK_SERVICE]: NewTaskLinkService;
  [MAIN_APPROVAL_LINK_SERVICE]: ApprovalLinkService;
  [MAIN_OPEN_TARGET_LINK_SERVICE]: OpenTargetLinkService;
  [MAIN_CANVAS_LINK_SERVICE]: CanvasLinkService;
  [MAIN_CHANNEL_LINK_SERVICE]: ChannelLinkService;
  [TASK_LINK_SERVICE]: TaskLinkService;
  [INBOX_LINK_SERVICE]: InboxLinkService;
  [SCOUT_LINK_SERVICE]: ScoutLinkService;
  [NEW_TASK_LINK_SERVICE]: NewTaskLinkService;
  [APPROVAL_LINK_SERVICE]: ApprovalLinkService;
  [OPEN_TARGET_LINK_SERVICE]: OpenTargetLinkService;
  [CANVAS_LINK_SERVICE]: CanvasLinkService;
  [CHANNEL_LINK_SERVICE]: ChannelLinkService;

  // Watcher registry
  [MAIN_WATCHER_REGISTRY_SERVICE]: WatcherRegistryService;

  // Workspace host ports
  [WORKSPACE_AGENT]: WorkspaceAgent;
  [WORKSPACE_FILE_WATCHER]: WorkspaceFileWatcher;
  [WORKSPACE_FOCUS]: WorkspaceFocus;
  [WORKSPACE_PROVISIONING]: WorkspaceProvisioning;
  [MAIN_WORKSPACE_SERVICE]: WorkspaceService;
  [MAIN_WORKSPACE_SERVER_SERVICE]: WorkspaceServerService;

  // Stores / secure store / encryption
  [MAIN_SETTINGS_STORE]: typeof settingsStore;
  [MAIN_SECURE_STORE_BACKEND]: typeof rendererStore;
  [MAIN_SECURE_STORE_SERVICE]: SecureStoreService;
  [SECURE_STORE_SERVICE]: ISecureStoreService;
  [SPEECH_SYNTHESIZER_SERVICE]: ISpeechSynthesizer;
  [LOGS_SERVICE]: ILogsService;
  [MAIN_ENCRYPTION_SERVICE]: EncryptionService;
  [MAIN_DISCORD_PRESENCE_SERVICE]: DiscordPresenceService;

  // Dev toolbar diagnostics
  [MAIN_DEV_FLAGS_SERVICE]: DevFlagsService;
  [MAIN_DEV_METRICS_SERVICE]: DevMetricsService;
  [MAIN_DEV_NETWORK_SERVICE]: DevNetworkService;
  [MAIN_DEV_LOGS_SERVICE]: DevLogsService;
  [MAIN_DEV_ACTIONS_SERVICE]: DevActionsService;

  // ws-server git service (bound to(GitService))
  [WS_GIT_SERVICE]: GitService;

  // index.ts runtime bindings
  [MAIN_WORKSPACE_CLIENT]: WorkspaceClient;
  [GIT_WORKSPACE_CLIENT]: HostGitWorkspaceClient;
  [CONNECTIVITY_CLIENT]: HostConnectivityClient;
  [ENVIRONMENT_CLIENT]: HostEnvironmentClient;
  [MAIN_FILE_WATCHER_SERVICE]: FileWatcherBridge;
  [FILE_WATCHER_CONTROL]: HostFileWatcherControl;
  [FOCUS_WORKSPACE_CLIENT]: FocusWorkspaceClient;
  [FOCUS_SESSION_STORE]: FocusSessionStore;
  [FOCUS_WORKTREE_PATHS]: FocusWorktreePaths;
  [MAIN_FS_SERVICE]: FsCapability;
  [FS_SERVICE]: FsCapability;

  // Typed container.get-only tokens (bound via loaded modules)
  [AGENT_SERVICE]: AgentService;
  [OAUTH_SERVICE]: OAuthService;
  [GITHUB_INTEGRATION_SERVICE]: GitHubIntegrationService;
  [SLACK_INTEGRATION_SERVICE]: SlackIntegrationService;
  [UI_SERVICE]: UIService;
  [MCP_APPS_SERVICE]: McpAppsService;
  [SUSPENSION_SERVICE]: SuspensionService;
}

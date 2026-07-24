import type { TrpcRouter } from "@main/trpc/router";
import {
  ARCHIVE_CLIENT,
  type ArchiveClient,
} from "@posthog/core/archive/identifiers";
import type { AutoresearchService } from "@posthog/core/autoresearch/autoresearch";
import {
  AUTORESEARCH_GATE,
  AUTORESEARCH_SERVICE,
  AUTORESEARCH_SESSION_CLIENT,
  AUTORESEARCH_STORAGE_CLIENT,
  type AutoresearchGate,
  type AutoresearchSessionClient,
  type AutoresearchStorageClient,
} from "@posthog/core/autoresearch/identifiers";
import {
  CODE_REVIEW_WORKSPACE_CLIENT,
  REVERT_HUNK_SERVICE,
} from "@posthog/core/code-review/identifiers";
import type {
  CodeReviewWorkspaceClient,
  RevertHunkService,
} from "@posthog/core/code-review/revertHunkService";
import {
  GITHUB_ISSUE_CLIENT,
  type GitHubIssueClient,
  NEW_TASK_LINK_RESOLVER,
} from "@posthog/core/deep-links/identifiers";
import type { NewTaskLinkResolver } from "@posthog/core/deep-links/newTaskLinkResolver";
import type { ReadFileAsBase64 } from "@posthog/core/editor/cloud-prompt";
import type { ExternalAppService } from "@posthog/core/external-apps/externalAppService";
import {
  EXTERNAL_APPS_FOCUS_COORDINATOR,
  EXTERNAL_APPS_SERVICE,
  EXTERNAL_APPS_WORKSPACE_CLIENT,
  type ExternalAppsWorkspaceClient,
} from "@posthog/core/external-apps/identifiers";
import type {
  GitInteractionEffects,
  GitInteractionService,
  IGitWriteClient,
} from "@posthog/core/git-interaction/gitInteractionService";
import {
  GIT_INTERACTION_EFFECTS,
  GIT_INTERACTION_SERVICE,
  GIT_WRITE_CLIENT,
} from "@posthog/core/git-interaction/identifiers";
import {
  LINEAR_OAUTH_FLOW,
  type LinearOAuthFlow,
  REPORT_MODEL_RESOLVER,
  type ReportModelResolver,
} from "@posthog/core/inbox/identifiers";
import {
  GITHUB_CONNECT_CLIENT as INTEGRATIONS_GITHUB_CONNECT_CLIENT,
  type GithubConnectClient as IntegrationsGithubConnectClient,
  REPOSITORIES_CLIENT,
  REPOSITORIES_SERVICE,
  type RepositoriesClient,
} from "@posthog/core/integrations/identifiers";
import type { RepositoriesService } from "@posthog/core/integrations/repositoriesService";
import { LLM_GATEWAY_SERVICE } from "@posthog/core/llm-gateway/identifiers";
import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import {
  LOCAL_MCP_IMPORT_SERVICE,
  LOCAL_MCP_WORKSPACE_CLIENT,
} from "@posthog/core/local-mcp/identifiers";
import type {
  LocalMcpImportService,
  LocalMcpWorkspaceClient,
} from "@posthog/core/local-mcp/localMcpImport";
import {
  GITHUB_CONNECT_CLIENT,
  type GithubConnectClient,
} from "@posthog/core/onboarding/identifiers";
import { PI_RUNNER } from "@posthog/core/pi-runtime/identifiers";
import type { PiRunner } from "@posthog/core/pi-runtime/piRunner";
import {
  PI_SESSION_CLIENT,
  type PiSessionClient,
} from "@posthog/core/pi-runtime/piSessionController";
import {
  type BundleLocalSkill,
  CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL,
  CLOUD_ARTIFACT_READ_FILE_AS_BASE64,
  CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES,
  type ResolveSkillBundleDependencies,
} from "@posthog/core/sessions/cloudArtifactIdentifiers";
import {
  LOCAL_HANDOFF_DIALOG,
  LOCAL_HANDOFF_HOST,
  LOCAL_HANDOFF_NOTIFIER,
  LOCAL_HANDOFF_SERVICE,
  type LocalHandoffDialog,
  type LocalHandoffHost,
  type LocalHandoffNotifier,
  type LocalHandoffService,
} from "@posthog/core/sessions/localHandoffService";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import type {
  FileReadClient,
  TitleGeneratorLogger,
} from "@posthog/core/sessions/titleGeneratorIdentifiers";
import {
  TITLE_GENERATOR_FILE_READ_CLIENT,
  TITLE_GENERATOR_LOGGER,
} from "@posthog/core/sessions/titleGeneratorIdentifiers";
import { type ISetupStore, SETUP_STORE } from "@posthog/core/setup/identifiers";
import { SKILLS_WORKSPACE_CLIENT } from "@posthog/core/skills/identifiers";
import type { SkillsWorkspaceClient } from "@posthog/core/skills/teamSkillsService";
import {
  SPEECH_SETTINGS_PROVIDER,
  SPEECH_USER_NAME_PROVIDER,
  type SpeechSettingsProvider,
  type UserNameProvider,
} from "@posthog/core/speech/identifiers";
import {
  TASK_CREATION_EFFECTS,
  TASK_CREATION_HOST,
  WORKSPACE_SETUP_SAGA,
} from "@posthog/core/task-detail/identifiers";
import type { TaskCreationEffects } from "@posthog/core/task-detail/taskCreationEffects";
import type { ITaskCreationHost } from "@posthog/core/task-detail/taskCreationHost";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import type { WorkspaceSetupSaga } from "@posthog/core/task-detail/workspaceSetupSaga";
import {
  type ITaskDeletionHost,
  type ITaskDeletionWorkspaceClient,
  TASK_DELETION_HOST,
  TASK_DELETION_SERVICE,
  TASK_DELETION_WORKSPACE_CLIENT,
} from "@posthog/core/tasks/identifiers";
import type { TaskDeletionService } from "@posthog/core/tasks/taskDeletionService";
import {
  SHELL_PROCESS_READER,
  type ShellProcessReader,
} from "@posthog/core/terminal/identifiers";
import {
  WORKSPACE_SETUP_GIT_CLIENT,
  WORKSPACE_SETUP_SERVICE,
  type WorkspaceSetupGitClient,
} from "@posthog/core/workspace/identifiers";
import type { WorkspaceSetupService } from "@posthog/core/workspace/WorkspaceSetupService";
import { CONTRIBUTION, type Contribution } from "@posthog/di/contribution";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import {
  HOST_CAPABILITIES,
  type HostCapabilities,
} from "@posthog/platform/host-capabilities";
import {
  type INotifications,
  NOTIFICATIONS_SERVICE,
} from "@posthog/platform/notifications";
import { type ISpeech, SPEECH_SERVICE } from "@posthog/platform/speech";
import {
  AUTH_SIDE_EFFECTS,
  type IAuthSideEffects,
} from "@posthog/ui/features/auth/identifiers";
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
import type { FocusStoreCoordinator } from "@posthog/ui/features/external-apps/focusCoordinator";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import {
  FILE_WATCHER_CLIENT,
  type FileWatcherClient,
} from "@posthog/ui/features/file-watcher/identifiers";
import {
  FOCUS_CONTROLLER_DEPS,
  type FocusControllerDeps,
} from "@posthog/ui/features/focus/focusClient";
import {
  GIT_CACHE_KEY_PROVIDER,
  type GitCacheKeyProvider,
} from "@posthog/ui/features/git-interaction/gitCacheProvider";
import {
  MCP_APP_HOST_COMPONENT,
  MCP_SANDBOX_PROXY_URL,
  type McpAppHostComponent,
  type McpSandboxProxyUrlProvider,
} from "@posthog/ui/features/mcp-apps/identifiers";
import {
  NAVIGATION_TASK_BINDER,
  type NavigationTaskBinder,
} from "@posthog/ui/features/navigation/taskBinder";
import {
  ACTIVE_VIEW_PROVIDER,
  type IActiveView,
  type INotificationSettings,
  type ISpeechNotifySettings,
  NOTIFICATION_SETTINGS_PROVIDER,
  SPEECH_NOTIFY_SETTINGS,
} from "@posthog/ui/features/notifications/identifiers";
import {
  AGENT_PROMPT_SENDER,
  type AgentPromptSender,
} from "@posthog/ui/features/sessions/agentPromptSender";
import {
  MCP_TOOL_BLOCK_COMPONENT,
  type McpToolBlockComponent,
} from "@posthog/ui/features/sessions/components/session-update/identifiers";
import {
  DEV_MODE_CLIENT,
  type DevModeClient,
} from "@posthog/ui/features/settings/devModeClient";
import {
  type ISpeechKeyStore,
  SPEECH_KEY_STORE,
} from "@posthog/ui/features/settings/speechKeyStore";
import {
  SHELL_CLIENT,
  type ShellClient,
} from "@posthog/ui/features/terminal/shellClient";
import {
  UPDATES_CLIENT,
  type UpdatesClient,
} from "@posthog/ui/features/updates/updatesClient";
import {
  ANALYTICS_TRACKER,
  type AnalyticsTracker,
} from "@posthog/ui/shell/analytics";
import {
  DIFF_WORKER_FACTORY,
  type DiffWorkerFactory,
} from "@posthog/ui/shell/diffWorkerHost";
import {
  HEDGEHOG_MODE_HOST,
  type HedgehogModeHost,
} from "@posthog/ui/shell/hedgehogModeHost";
import { HOST_LOGGER, type HostLogger } from "@posthog/ui/shell/logger";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import {
  FILE_PATH_RESOLVER,
  type FilePathResolver,
} from "@posthog/ui/utils/getFilePath";
import type { TRPCClient } from "@trpc/client";
import { TASK_SERVICE as RENDERER_TASK_SERVICE, TRPC_CLIENT } from "./tokens";

/**
 * Strongly-typed binding map for the renderer composition-root container.
 *
 * Covers every token directly bound on the renderer `container` across
 * `di/container.ts`, `desktop-services.ts`, and
 * `desktop-contributions.ts`. Tokens resolved purely through plain
 * `container.load(module)` are not listed here (TypedContainer accepts plain
 * ContainerModules without typing their internal bindings).
 */
export interface RendererBindings {
  // --- di/container.ts ---
  [HOST_LOGGER]: HostLogger;
  [TRPC_CLIENT]: TRPCClient<TrpcRouter>;
  [HOST_TRPC_CLIENT]: HostTrpcClient;
  [UPDATES_CLIENT]: UpdatesClient;
  [DEV_MODE_CLIENT]: DevModeClient;
  [CONNECTIVITY_CLIENT]: ConnectivityClient;
  [BROWSER_TABS_CLIENT]: BrowserTabsClient;
  [DISCORD_PRESENCE_CLIENT]: DiscordPresenceClient;
  [SHELL_CLIENT]: ShellClient;
  [FOCUS_CONTROLLER_DEPS]: FocusControllerDeps;
  [DIFF_WORKER_FACTORY]: DiffWorkerFactory;
  [REVIEW_HOST]: ReviewHost;
  [MCP_TOOL_BLOCK_COMPONENT]: McpToolBlockComponent;
  [MCP_APP_HOST_COMPONENT]: McpAppHostComponent;
  [MCP_SANDBOX_PROXY_URL]: McpSandboxProxyUrlProvider;
  [SHELL_PROCESS_READER]: ShellProcessReader;
  [ANALYTICS_TRACKER]: AnalyticsTracker;
  [TASK_CREATION_HOST]: ITaskCreationHost;
  [PI_RUNNER]: PiRunner;
  [PI_SESSION_CLIENT]: PiSessionClient;
  [TASK_CREATION_EFFECTS]: TaskCreationEffects;
  [RENDERER_TASK_SERVICE]: TaskService;
  [TASK_SERVICE]: TaskService;
  [WORKSPACE_SETUP_SAGA]: WorkspaceSetupSaga;
  [SESSION_SERVICE]: SessionService;
  [LOCAL_HANDOFF_HOST]: LocalHandoffHost;
  [LOCAL_HANDOFF_DIALOG]: LocalHandoffDialog;
  [LOCAL_HANDOFF_NOTIFIER]: LocalHandoffNotifier;
  [LOCAL_HANDOFF_SERVICE]: LocalHandoffService;
  [GIT_WRITE_CLIENT]: IGitWriteClient;
  [GIT_INTERACTION_EFFECTS]: GitInteractionEffects;
  [GIT_INTERACTION_SERVICE]: GitInteractionService;
  [TASK_DELETION_WORKSPACE_CLIENT]: ITaskDeletionWorkspaceClient;
  [TASK_DELETION_HOST]: ITaskDeletionHost;
  [TASK_DELETION_SERVICE]: TaskDeletionService;
  [EXTERNAL_APPS_WORKSPACE_CLIENT]: ExternalAppsWorkspaceClient;
  [EXTERNAL_APPS_FOCUS_COORDINATOR]: FocusStoreCoordinator;
  [EXTERNAL_APPS_SERVICE]: ExternalAppService;
  [WORKSPACE_SETUP_GIT_CLIENT]: WorkspaceSetupGitClient;
  [WORKSPACE_SETUP_SERVICE]: WorkspaceSetupService;
  [GITHUB_ISSUE_CLIENT]: GitHubIssueClient;
  [NEW_TASK_LINK_RESOLVER]: NewTaskLinkResolver;
  [CODE_REVIEW_WORKSPACE_CLIENT]: CodeReviewWorkspaceClient;
  [REVERT_HUNK_SERVICE]: RevertHunkService;
  [SKILLS_WORKSPACE_CLIENT]: SkillsWorkspaceClient;
  [LOCAL_MCP_WORKSPACE_CLIENT]: LocalMcpWorkspaceClient;
  [LOCAL_MCP_IMPORT_SERVICE]: LocalMcpImportService;
  [CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL]: BundleLocalSkill;
  [CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES]: ResolveSkillBundleDependencies;
  [CLOUD_ARTIFACT_READ_FILE_AS_BASE64]: ReadFileAsBase64;
  [LLM_GATEWAY_SERVICE]: LlmGatewayService;
  [TITLE_GENERATOR_FILE_READ_CLIENT]: FileReadClient;
  [TITLE_GENERATOR_LOGGER]: TitleGeneratorLogger;

  // --- desktop-services.ts ---
  [IMPERATIVE_QUERY_CLIENT]: ImperativeQueryClient;
  [GIT_CACHE_KEY_PROVIDER]: GitCacheKeyProvider;
  [ARCHIVE_CLIENT]: ArchiveClient;
  [REPORT_MODEL_RESOLVER]: ReportModelResolver;
  [LINEAR_OAUTH_FLOW]: LinearOAuthFlow;
  [GITHUB_CONNECT_CLIENT]: GithubConnectClient;
  [INTEGRATIONS_GITHUB_CONNECT_CLIENT]: IntegrationsGithubConnectClient;
  [REPOSITORIES_CLIENT]: RepositoriesClient;
  [REPOSITORIES_SERVICE]: RepositoriesService;
  [HEDGEHOG_MODE_HOST]: HedgehogModeHost;
  [AGENT_PROMPT_SENDER]: AgentPromptSender;
  [AUTORESEARCH_SESSION_CLIENT]: AutoresearchSessionClient;
  [AUTORESEARCH_STORAGE_CLIENT]: AutoresearchStorageClient;
  [AUTORESEARCH_GATE]: AutoresearchGate;
  [FILE_PATH_RESOLVER]: FilePathResolver;
  [NAVIGATION_TASK_BINDER]: NavigationTaskBinder;
  [ROOT_LOGGER]: RootLogger;
  [NOTIFICATIONS_SERVICE]: INotifications;
  [NOTIFICATION_SETTINGS_PROVIDER]: INotificationSettings;
  [ACTIVE_VIEW_PROVIDER]: IActiveView;
  [SPEECH_SERVICE]: ISpeech;
  [SPEECH_SETTINGS_PROVIDER]: SpeechSettingsProvider;
  [SPEECH_USER_NAME_PROVIDER]: UserNameProvider;
  [SPEECH_NOTIFY_SETTINGS]: ISpeechNotifySettings;
  [SPEECH_KEY_STORE]: ISpeechKeyStore;
  [FILE_WATCHER_CLIENT]: FileWatcherClient;
  [FEATURE_FLAGS]: FeatureFlags;
  [AUTH_SIDE_EFFECTS]: IAuthSideEffects;
  [SETUP_STORE]: ISetupStore;
  [HOST_CAPABILITIES]: HostCapabilities;

  // --- desktop-contributions.ts ---
  [CONTRIBUTION]: Contribution;
  [AUTORESEARCH_SERVICE]: AutoresearchService;
}

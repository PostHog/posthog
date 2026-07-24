import "reflect-metadata";
import { TypedContainer } from "@inversifyjs/strongly-typed";
import { DEFAULT_GATEWAY_MODEL } from "@posthog/agent/gateway-models";
import {
  getGatewayUsageUrl,
  getLlmGatewayUrl,
} from "@posthog/agent/posthog-api";
import { archiveModule } from "@posthog/core/archive/archive.module";
import {
  ARCHIVE_CLIENT,
  type ArchiveClient,
} from "@posthog/core/archive/identifiers";
import type { AuthService } from "@posthog/core/auth/auth";
import { AUTH_SERVICE, authCoreModule } from "@posthog/core/auth/auth.module";
import {
  AUTH_CONNECTIVITY,
  AUTH_OAUTH_FLOW_SERVICE,
  AUTH_PREFERENCE_STORE,
  AUTH_SESSION_STORE,
  AUTH_TOKEN_CIPHER,
  AUTH_TOKEN_OVERRIDE,
  type IAuthConnectivity,
  type IAuthOAuthFlowService,
  type IAuthPreferenceStore,
  type IAuthSessionStore,
  type IAuthTokenCipher,
} from "@posthog/core/auth/identifiers";
import { canvasCoreModule } from "@posthog/core/canvas/canvas.module";
import { taskThreadCoreModule } from "@posthog/core/canvas/taskThread.module";
import type { CloudTaskService } from "@posthog/core/cloud-task/cloud-task";
import { cloudTaskModule } from "@posthog/core/cloud-task/cloud-task.module";
import {
  CLOUD_TASK_AUTH,
  CLOUD_TASK_SERVICE,
  type ICloudTaskAuth,
} from "@posthog/core/cloud-task/identifiers";
import { deepLinksCoreModule } from "@posthog/core/deep-links/deep-links.module";
import {
  GITHUB_ISSUE_CLIENT,
  type GitHubIssueClient,
} from "@posthog/core/deep-links/identifiers";
import type { ReadFileAsBase64 } from "@posthog/core/editor/cloud-prompt";
import { externalAppsCoreModule } from "@posthog/core/external-apps/external-apps.module";
import type { ExternalAppService } from "@posthog/core/external-apps/externalAppService";
import {
  EXTERNAL_APPS_FOCUS_COORDINATOR,
  EXTERNAL_APPS_SERVICE,
  EXTERNAL_APPS_WORKSPACE_CLIENT,
  type ExternalAppsFocusCoordinator,
  type ExternalAppsWorkspaceClient,
} from "@posthog/core/external-apps/identifiers";
import { gitInteractionModule } from "@posthog/core/git-interaction/git-interaction.module";
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
  REPORT_MODEL_RESOLVER,
  type ReportModelResolver,
} from "@posthog/core/inbox/identifiers";
import { selectModelFromOptions } from "@posthog/core/inbox/reportTaskCreation";
import { githubConnectModule } from "@posthog/core/integrations/githubConnect.module";
import {
  GITHUB_CONNECT_CLIENT as INTEGRATIONS_GITHUB_CONNECT_CLIENT,
  type GithubConnectClient as IntegrationsGithubConnectClient,
  REPOSITORIES_CLIENT,
  REPOSITORIES_SERVICE,
  type RepositoriesClient,
} from "@posthog/core/integrations/identifiers";
import { RepositoriesService } from "@posthog/core/integrations/repositoriesService";
import {
  LLM_GATEWAY_HOST,
  LLM_GATEWAY_SERVICE,
  type LlmGatewayHost,
} from "@posthog/core/llm-gateway/identifiers";
import type { LlmGatewayService } from "@posthog/core/llm-gateway/llm-gateway";
import { llmGatewayModule } from "@posthog/core/llm-gateway/llm-gateway.module";
import {
  GITHUB_CONNECT_CLIENT as ONBOARDING_GITHUB_CONNECT_CLIENT,
  type GithubConnectClient as OnboardingGithubConnectContract,
} from "@posthog/core/onboarding/identifiers";
import { onboardingModule } from "@posthog/core/onboarding/onboarding.module";
import { piRuntimeModule } from "@posthog/core/pi-runtime/pi-runtime.module";
import {
  PI_SESSION_CLIENT,
  type PiSessionClient,
} from "@posthog/core/pi-runtime/piSessionController";
import {
  type BundleLocalSkill,
  CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL,
  CLOUD_ARTIFACT_READ_FILE_AS_BASE64,
  CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES,
  CLOUD_ARTIFACT_SERVICE,
  type ResolveSkillBundleDependencies,
} from "@posthog/core/sessions/cloudArtifactIdentifiers";
import type { CloudArtifactService } from "@posthog/core/sessions/cloudArtifactService";
import {
  LOCAL_HANDOFF_DIALOG,
  LOCAL_HANDOFF_HOST,
  LOCAL_HANDOFF_NOTIFIER,
  LOCAL_HANDOFF_SERVICE,
  type LocalHandoffDialog,
  type LocalHandoffHost,
  type LocalHandoffNotifier,
  LocalHandoffService,
} from "@posthog/core/sessions/localHandoffService";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { sessionsModule } from "@posthog/core/sessions/sessions.module";
import {
  type FileReadClient,
  TITLE_GENERATOR_FILE_READ_CLIENT,
  TITLE_GENERATOR_LOGGER,
  TITLE_GENERATOR_SERVICE,
  type TitleGeneratorLogger,
} from "@posthog/core/sessions/titleGeneratorIdentifiers";
import type { TitleGeneratorService } from "@posthog/core/sessions/titleGeneratorService";
import { type ISetupStore, SETUP_STORE } from "@posthog/core/setup/identifiers";
import { setupCoreModule } from "@posthog/core/setup/setup.module";
import {
  SKILLS_WORKSPACE_CLIENT,
  TEAM_SKILLS_SERVICE,
} from "@posthog/core/skills/identifiers";
import { skillsCoreModule } from "@posthog/core/skills/skills.module";
import type {
  SkillsWorkspaceClient,
  TeamSkillsService,
} from "@posthog/core/skills/teamSkillsService";
import {
  TASK_CREATION_EFFECTS,
  TASK_CREATION_HOST,
  TASK_SERVICE,
  WORKSPACE_SETUP_SAGA,
} from "@posthog/core/task-detail/identifiers";
import { taskDetailModule } from "@posthog/core/task-detail/task-detail.module";
import type { TaskCreationEffects } from "@posthog/core/task-detail/taskCreationEffects";
import type { ITaskCreationHost } from "@posthog/core/task-detail/taskCreationHost";
import type { TaskService as TaskServiceType } from "@posthog/core/task-detail/taskService";
import type { WorkspaceSetupSaga } from "@posthog/core/task-detail/workspaceSetupSaga";
import {
  type ITaskDeletionHost,
  type ITaskDeletionWorkspaceClient,
  TASK_DELETION_HOST,
  TASK_DELETION_SERVICE,
  TASK_DELETION_WORKSPACE_CLIENT,
} from "@posthog/core/tasks/identifiers";
import type { TaskDeletionService } from "@posthog/core/tasks/taskDeletionService";
import { tasksModule } from "@posthog/core/tasks/tasks.module";
import { setRootContainer } from "@posthog/di/container";
import { assertHostCapabilities } from "@posthog/di/hostCapabilities";
import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { TrpcPiSessionClient } from "@posthog/host-router/pi-session-client";
import {
  ANALYTICS_SERVICE,
  type IAnalytics,
} from "@posthog/platform/analytics";
import {
  HOST_CAPABILITIES,
  type HostCapabilities,
} from "@posthog/platform/host-capabilities";
import {
  type INotifications,
  NOTIFICATIONS_SERVICE,
} from "@posthog/platform/notifications";
import {
  type IPowerManager,
  POWER_MANAGER_SERVICE,
} from "@posthog/platform/power-manager";
import { type Adapter, SYNC_CLOUD_TASKS_FLAG } from "@posthog/shared";
import { sandboxProxyHtml } from "@posthog/shared/mcp-sandbox-proxy";
import { authUiModule } from "@posthog/ui/features/auth/auth.module";
import {
  AUTH_SIDE_EFFECTS,
  type IAuthSideEffects,
} from "@posthog/ui/features/auth/identifiers";
import { browserTabsUiModule } from "@posthog/ui/features/browser-tabs/browser-tabs.module";
import {
  BROWSER_TABS_CLIENT,
  type BrowserTabsClient,
} from "@posthog/ui/features/browser-tabs/browserTabsClient";
import {
  REVIEW_HOST,
  type ReviewHost,
} from "@posthog/ui/features/code-review/reviewHost";
import { connectivityUiModule } from "@posthog/ui/features/connectivity/connectivity.module";
import {
  CONNECTIVITY_CLIENT,
  type ConnectivityClient,
} from "@posthog/ui/features/connectivity/connectivityClient";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import {
  FILE_WATCHER_CLIENT,
  type FileWatcherClient,
} from "@posthog/ui/features/file-watcher/identifiers";
import {
  GIT_CACHE_KEY_PROVIDER,
  type GitCacheKeyProvider,
} from "@posthog/ui/features/git-interaction/gitCacheProvider";
import {
  gitInteractionEffects,
  gitWriteClient,
} from "@posthog/ui/features/git-interaction/gitInteractionAdapter";
import {
  UiGithubConnectClient,
  UiRepositoriesClient,
} from "@posthog/ui/features/integrations/integrationsClientImpl";
import { McpAppHost } from "@posthog/ui/features/mcp-apps/components/McpAppHost";
import {
  MCP_APP_HOST_COMPONENT,
  MCP_SANDBOX_PROXY_URL,
  type McpAppHostComponent,
  type McpSandboxProxyUrlProvider,
} from "@posthog/ui/features/mcp-apps/identifiers";
import {
  ACTIVE_VIEW_PROVIDER,
  type IActiveView,
  type INotificationSettings,
  NOTIFICATION_SETTINGS_PROVIDER,
} from "@posthog/ui/features/notifications/identifiers";
import { notificationsUiModule } from "@posthog/ui/features/notifications/notifications.module";
import { OnboardingGithubConnectClient } from "@posthog/ui/features/onboarding/githubConnectClientImpl";
import {
  localHandoffDialog,
  localHandoffNotifier,
} from "@posthog/ui/features/sessions/localHandoffService";
import { getSessionService } from "@posthog/ui/features/sessions/sessionServiceHost";
import { setupUiModule } from "@posthog/ui/features/setup/setup.module";
import { taskCreationEffects } from "@posthog/ui/features/task-detail/taskCreationEffectsImpl";
import { TrpcTaskCreationHost } from "@posthog/ui/features/task-detail/taskCreationHostImpl";
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
  posthogAnalyticsService,
  posthogAnalyticsTracker,
  posthogFeatureFlags,
} from "@posthog/ui/shell/posthogAnalyticsImpl";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "@posthog/ui/shell/queryClient";
import { REQUIRED_HOST_CAPABILITIES } from "@posthog/ui/shell/requiredHostCapabilities";
import { QueryClient } from "@tanstack/react-query";
import {
  WebAuthConnectivity,
  WebAuthPreferenceStore,
  WebAuthSessionStore,
  webAuthTokenCipher,
  webPowerManager,
} from "./web-auth-adapters";
import { WebAuthSideEffects } from "./web-auth-side-effects";
import { webBrowserTabsStore } from "./web-browser-tabs-store";
import { webConnectivityClient } from "./web-connectivity-client";
import {
  webExternalAppsFocusCoordinator,
  webExternalAppsWorkspaceClient,
} from "./web-external-apps";
import { webGitCacheKeyProvider } from "./web-git-cache-keys";
import {
  webActiveView,
  webNotificationSettings,
  webNotifications,
} from "./web-notifications";
import { WebOAuthFlowService } from "./web-oauth-flow";
import { webDiffWorkerFactory, webReviewHost } from "./web-review-host";
import {
  webBundleLocalSkill,
  webReadFileAsBase64,
  webResolveSkillBundleDependencies,
  webTitleGeneratorFileReadClient,
  webTitleGeneratorLogger,
} from "./web-sessions-clients";
import { webSetupStore } from "./web-setup-store";
import { webShellClient } from "./web-shell-client";
import {
  webTaskDeletionHost,
  webTaskDeletionWorkspaceClient,
} from "./web-task-deletion";
import { hostTrpcClient } from "./web-trpc";

interface WebBindings {
  [HOST_TRPC_CLIENT]: HostTrpcClient;
  [PI_SESSION_CLIENT]: PiSessionClient;
  [ROOT_LOGGER]: RootLogger;
  [HOST_LOGGER]: HostLogger;
  [FEATURE_FLAGS]: FeatureFlags;
  [ANALYTICS_TRACKER]: AnalyticsTracker;
  [ANALYTICS_SERVICE]: IAnalytics;
  [IMPERATIVE_QUERY_CLIENT]: ImperativeQueryClient;
  [AUTH_SIDE_EFFECTS]: IAuthSideEffects;
  [MCP_APP_HOST_COMPONENT]: McpAppHostComponent;
  [MCP_SANDBOX_PROXY_URL]: McpSandboxProxyUrlProvider;
  [AUTH_SESSION_STORE]: IAuthSessionStore;
  [AUTH_PREFERENCE_STORE]: IAuthPreferenceStore;
  [AUTH_OAUTH_FLOW_SERVICE]: IAuthOAuthFlowService;
  [AUTH_TOKEN_CIPHER]: IAuthTokenCipher;
  [AUTH_CONNECTIVITY]: IAuthConnectivity;
  [AUTH_TOKEN_OVERRIDE]: string | null;
  [POWER_MANAGER_SERVICE]: IPowerManager;
  [AUTH_SERVICE]: AuthService;
  [CLOUD_TASK_SERVICE]: CloudTaskService;
  [CLOUD_TASK_AUTH]: ICloudTaskAuth;
  [SESSION_SERVICE]: SessionService;
  [SETUP_STORE]: ISetupStore;
  [GITHUB_ISSUE_CLIENT]: GitHubIssueClient;
  [HEDGEHOG_MODE_HOST]: HedgehogModeHost;
  [INTEGRATIONS_GITHUB_CONNECT_CLIENT]: IntegrationsGithubConnectClient;
  [ONBOARDING_GITHUB_CONNECT_CLIENT]: OnboardingGithubConnectContract;
  [REPOSITORIES_CLIENT]: RepositoriesClient;
  [REPOSITORIES_SERVICE]: RepositoriesService;
  [HOST_CAPABILITIES]: HostCapabilities;
  [TASK_SERVICE]: TaskServiceType;
  [WORKSPACE_SETUP_SAGA]: WorkspaceSetupSaga;
  [TASK_CREATION_HOST]: ITaskCreationHost;
  [TASK_CREATION_EFFECTS]: TaskCreationEffects;
  [CONNECTIVITY_CLIENT]: ConnectivityClient;
  [BROWSER_TABS_CLIENT]: BrowserTabsClient;
  [EXTERNAL_APPS_SERVICE]: ExternalAppService;
  [EXTERNAL_APPS_WORKSPACE_CLIENT]: ExternalAppsWorkspaceClient;
  [EXTERNAL_APPS_FOCUS_COORDINATOR]: ExternalAppsFocusCoordinator;
  [TASK_DELETION_SERVICE]: TaskDeletionService;
  [TASK_DELETION_WORKSPACE_CLIENT]: ITaskDeletionWorkspaceClient;
  [TASK_DELETION_HOST]: ITaskDeletionHost;
  [SHELL_CLIENT]: ShellClient;
  [ARCHIVE_CLIENT]: ArchiveClient;
  [UPDATES_CLIENT]: UpdatesClient;
  [GIT_CACHE_KEY_PROVIDER]: GitCacheKeyProvider;
  [TEAM_SKILLS_SERVICE]: TeamSkillsService;
  [SKILLS_WORKSPACE_CLIENT]: SkillsWorkspaceClient;
  [CLOUD_ARTIFACT_SERVICE]: CloudArtifactService;
  [CLOUD_ARTIFACT_READ_FILE_AS_BASE64]: ReadFileAsBase64;
  [CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL]: BundleLocalSkill;
  [CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES]: ResolveSkillBundleDependencies;
  [TITLE_GENERATOR_SERVICE]: TitleGeneratorService;
  [TITLE_GENERATOR_FILE_READ_CLIENT]: FileReadClient;
  [TITLE_GENERATOR_LOGGER]: TitleGeneratorLogger;
  [LLM_GATEWAY_SERVICE]: LlmGatewayService;
  [LLM_GATEWAY_HOST]: LlmGatewayHost;
  [LOCAL_HANDOFF_SERVICE]: LocalHandoffService;
  [LOCAL_HANDOFF_HOST]: LocalHandoffHost;
  [LOCAL_HANDOFF_DIALOG]: LocalHandoffDialog;
  [LOCAL_HANDOFF_NOTIFIER]: LocalHandoffNotifier;
  [FILE_WATCHER_CLIENT]: FileWatcherClient;
  [GIT_INTERACTION_SERVICE]: GitInteractionService;
  [GIT_WRITE_CLIENT]: IGitWriteClient;
  [GIT_INTERACTION_EFFECTS]: GitInteractionEffects;
  [DIFF_WORKER_FACTORY]: DiffWorkerFactory;
  [REVIEW_HOST]: ReviewHost;
  [NOTIFICATIONS_SERVICE]: INotifications;
  [NOTIFICATION_SETTINGS_PROVIDER]: INotificationSettings;
  [ACTIVE_VIEW_PROVIDER]: IActiveView;
  [REPORT_MODEL_RESOLVER]: ReportModelResolver;
}

export const queryClient = new QueryClient();

export const container = new TypedContainer<WebBindings>({
  defaultScope: "Singleton",
});

// Keystone: the same typed host client the renderer binds — served in-process
// here (web-trpc.ts) instead of over Electron IPC.
container.bind(HOST_TRPC_CLIENT).toConstantValue(hostTrpcClient);
container.bind(PI_SESSION_CLIENT).to(TrpcPiSessionClient);
container.load(piRuntimeModule);

// Logger: web uses console; electron uses electron-log. Same RootLogger shape.
const scoped = (name?: string): RootLogger => ({
  debug: (...a) => console.debug(name ? `[${name}]` : "", ...a),
  info: (...a) => console.info(name ? `[${name}]` : "", ...a),
  warn: (...a) => console.warn(name ? `[${name}]` : "", ...a),
  error: (...a) => console.error(name ? `[${name}]` : "", ...a),
  scope: (n: string) => scoped(n),
});
container.bind(ROOT_LOGGER).toConstantValue(scoped());
// @posthog/ui's shell logger resolves HOST_LOGGER separately; bind it to the
// same console logger so UI-side errors (e.g. failed mutations) actually surface
// instead of silently no-op'ing.
container.bind(HOST_LOGGER).toConstantValue(scoped());

// ── Auth: the portable core state machine over web adapters ──
// Desktop runs AuthService in the Electron main process (SQLite session store,
// machine-bound cipher, deep-link OAuth). Web runs the SAME service in the
// browser over localStorage adapters and a popup PKCE flow.
container.load(authCoreModule);
container.bind(AUTH_SESSION_STORE).toConstantValue(new WebAuthSessionStore());
container
  .bind(AUTH_PREFERENCE_STORE)
  .toConstantValue(new WebAuthPreferenceStore());
container
  .bind(AUTH_OAUTH_FLOW_SERVICE)
  .toConstantValue(new WebOAuthFlowService(scoped("web-oauth")));
container.bind(AUTH_TOKEN_CIPHER).toConstantValue(webAuthTokenCipher);
container.bind(AUTH_CONNECTIVITY).toConstantValue(new WebAuthConnectivity());
container
  .bind(AUTH_TOKEN_OVERRIDE)
  .toConstantValue(
    (import.meta.env.VITE_POSTHOG_ACCESS_TOKEN_OVERRIDE as
      | string
      | undefined) ?? null,
  );
container.bind(POWER_MANAGER_SERVICE).toConstantValue(webPowerManager);

// The web host is cloud-only: no local filesystem, so the UI must use remote
// (connected-GitHub-org) repositories and cloud workspaces everywhere it would
// otherwise reach for local folders/worktrees/terminal.
container
  .bind(HOST_CAPABILITIES)
  .toConstantValue({ localWorkspaces: false } satisfies HostCapabilities);

container.load(authUiModule);

// ── Cloud tasks: CloudTaskService is pure fetch/SSE core code ──
// Same wiring as apps/code's main container, minus Electron.
container.load(cloudTaskModule);
container.bind(CLOUD_TASK_AUTH).toDynamicValue((ctx) => ({
  authenticatedFetch: (url: string, init?: RequestInit) =>
    ctx
      .get<AuthService>(AUTH_SERVICE)
      .authenticatedFetch(
        (input, fetchInit) => fetch(input, fetchInit),
        url,
        init,
      ),
  getCloudContext: async () => {
    const auth = ctx.get<AuthService>(AUTH_SERVICE);
    const { apiHost } = await auth.getValidAccessToken();
    const teamId = auth.getState().currentProjectId;
    return teamId === null ? null : { apiHost, teamId };
  },
}));

// ── Canvas / Channels: host-agnostic dashboard + freeform canvas services ──
// They only need AuthService + fetch (they reach the PostHog desktop_file_system
// API), so the web host binds them by loading the same core module desktop does;
// the web host router forwards its canvas routers to these.
container.load(canvasCoreModule);
container.load(taskThreadCoreModule);

// SessionService is built from host-agnostic deps (host tRPC client + UI
// stores) — same construction the desktop renderer uses.
container
  .bind(SESSION_SERVICE)
  .toDynamicValue(() => getSessionService())
  .inSingletonScope();

// ── Feature flags (real posthog-js, with one host-forced flag) ──
container.bind(FEATURE_FLAGS).toConstantValue({
  // Cloud-task sync is a hard requirement of the cloud-only host — __root's
  // reconcile effect derives the (localStorage-backed) sidebar task list from it
  // — so force it on regardless of the remote flag, then defer every other flag
  // to posthog-js. When posthog isn't initialized (no real VITE_POSTHOG_API_KEY),
  // isEnabled returns false for everything else, so only the forced flag is on —
  // same behavior as the old stub, but real flags light up once a key is set.
  isEnabled: (flagKey: string) =>
    flagKey === SYNC_CLOUD_TASKS_FLAG || posthogFeatureFlags.isEnabled(flagKey),
  onFlagsLoaded: posthogFeatureFlags.onFlagsLoaded,
});

// ── Analytics + error tracking (real posthog-js) ──
// Both ports share the single posthog-js instance initialized in main.tsx (see
// initializePostHog). ANALYTICS_TRACKER is the UI-wide event/exception port;
// ANALYTICS_SERVICE is the platform port core services (cloud-task) report
// through. Desktop backs the platform port with posthog-node in its main
// process; web has no Node process, so it uses posthog-js for both. Both no-op
// until posthog is initialized with a real project key.
container.bind(ANALYTICS_TRACKER).toConstantValue(posthogAnalyticsTracker);
container.bind(ANALYTICS_SERVICE).toConstantValue(posthogAnalyticsService);
container.bind(IMPERATIVE_QUERY_CLIENT).toConstantValue(queryClient);

container.bind(AUTH_SIDE_EFFECTS).to(WebAuthSideEffects);

// Interactive MCP App iframe host. Electron isolates the proxy with a custom
// privileged scheme; web gets a separate origin for free via a blob URL of the
// same (host-agnostic) proxy HTML. The blob is created once, lazily.
container.bind(MCP_APP_HOST_COMPONENT).toConstantValue(McpAppHost);
let sandboxProxyUrl: string | null = null;
container.bind(MCP_SANDBOX_PROXY_URL).toConstantValue(() => {
  if (!sandboxProxyUrl) {
    sandboxProxyUrl = URL.createObjectURL(
      new Blob([sandboxProxyHtml], { type: "text/html" }),
    );
  }
  return sandboxProxyUrl;
});

// ── Post-login shell: the tokens __root.tsx resolves eagerly via useService ──
// The shared app shell (packages/ui __root.tsx) mounts the full desktop surface
// once authenticated+onboarded. These three are resolved synchronously in
// render, so an unbound token crashes the tree (unlike tRPC/query calls, which
// degrade to a rejected promise). Bind the real host-agnostic services where
// they exist and thin stubs for genuinely local-only host capabilities.

// Setup discovery (useSetupDiscovery at __root): SetupRunService is portable
// core; SetupRunServiceImpl talks to the PostHog API via HOST_TRPC_CLIENT; the
// store adapter is host-agnostic zustand, reused verbatim from desktop.
container.load(setupCoreModule);
container.load(setupUiModule);
container.bind(SETUP_STORE).toConstantValue(webSetupStore);

// New-task deep links (useNewTaskDeepLink at __root): the resolver is portable
// core, but its GITHUB_ISSUE_CLIENT dep reads a local git repo on desktop. Web
// has no git backend, so bind a stub that rejects if an "issue" deep link is
// ever resolved (the browser has no deep-link scheme, so this never fires).
container.load(deepLinksCoreModule);
container.bind(GITHUB_ISSUE_CLIENT).toConstantValue({
  getGithubIssue: () =>
    Promise.reject(new Error("GitHub issue lookup is not available on web")),
});

// Hedgehog overlay (HedgehogMode at __root): optional cosmetic canvas game the
// desktop adapter owns via @posthog/hedgehog-mode. Web binds a no-op host so
// the useService call resolves; nothing renders.
container.bind(HEDGEHOG_MODE_HOST).toConstantValue({
  mount: () =>
    Promise.resolve({ destroy: () => {}, isContextLost: () => false }),
});

// ── GitHub integration: onboarding connect step + __root's useIntegrations() ──
// Cloud tasks operate on GitHub repos, so these are REAL bindings backed by the
// PostHog API (api-client), not stubs. The onboarding and integrations features
// each define their own GITHUB_CONNECT_{CLIENT,SERVICE} tokens; both services
// are portable core and both client impls are host-agnostic, reused verbatim
// from the desktop renderer. RepositoriesService has no module, so bind it
// directly like desktop does.
container.load(githubConnectModule);
container.load(onboardingModule);
container
  .bind(INTEGRATIONS_GITHUB_CONNECT_CLIENT)
  .toConstantValue(new UiGithubConnectClient());
container
  .bind(ONBOARDING_GITHUB_CONNECT_CLIENT)
  .toConstantValue(new OnboardingGithubConnectClient());
container.bind(REPOSITORIES_CLIENT).toConstantValue(new UiRepositoriesClient());
container.bind(REPOSITORIES_SERVICE).to(RepositoriesService).inSingletonScope();

// ── Task list + creation (TASK_SERVICE at the task views) ──
// TaskService/WorkspaceSetupSaga are portable core (taskDetailModule). The
// creation host and effects are the same host-agnostic renderer impls desktop
// uses: TrpcTaskCreationHost drives everything through HOST_TRPC_CLIENT, and the
// effects touch only UI stores + the query client. Local-only host methods
// (workspace/folders/git) resolve to NOT_FOUND at call time, but the cloud
// creation path doesn't need them.
container.load(taskDetailModule);
container.bind(TASK_CREATION_HOST).to(TrpcTaskCreationHost);
container.bind(TASK_CREATION_EFFECTS).toConstantValue(taskCreationEffects);

// ── Connectivity (ConnectivityBanner at __root) ──
// Real web implementation over navigator.onLine + online/offline events. The
// module's contributions react to the same status changes.
container.load(connectivityUiModule);
container.bind(CONNECTIVITY_CLIENT).toConstantValue(webConnectivityClient);

// ── Browser tabs (BrowserTabStrip at __root) ──
// The UI module's contribution seeds and keeps the renderer tab mirror live via
// this client; without it the snapshot never loads, no window exists, and the
// "+" (new tab) button no-ops on its windowId guard. The client is a passthrough
// over the localStorage-backed store, which is the same singleton the host-router
// `browserTabs` slice forwards to — so both access paths stay in sync.
container.load(browserTabsUiModule);
const webBrowserTabsClient: BrowserTabsClient = {
  getSnapshot: () => Promise.resolve(webBrowserTabsStore.getSnapshot()),
  getPrimaryWindowId: () =>
    Promise.resolve(webBrowserTabsStore.getPrimaryWindowId()),
  openOrFocus: (input) =>
    Promise.resolve(webBrowserTabsStore.openOrFocus(input)),
  newBlankTab: (input) =>
    Promise.resolve(webBrowserTabsStore.newBlankTab(input)),
  setTabTarget: (input) =>
    Promise.resolve(webBrowserTabsStore.setTabTarget(input)),
  close: (tabId) => Promise.resolve(webBrowserTabsStore.close(tabId)),
  setActiveTab: (input) =>
    Promise.resolve(webBrowserTabsStore.setActiveTab(input)),
  onSnapshotChange: (sub) => {
    webBrowserTabsStore.on("snapshotChange", sub.onData);
    return {
      unsubscribe: () => webBrowserTabsStore.off("snapshotChange", sub.onData),
    };
  },
};
container.bind(BROWSER_TABS_CLIENT).toConstantValue(webBrowserTabsClient);

// ── External apps (sidebar's eager useExternalAppAction) ──
// Local-only feature (open in a local editor / reveal / copy local path). The
// real service resolves; its workspace + focus clients are web stubs since
// there is no local filesystem to open anything in.
container.load(externalAppsCoreModule);
container
  .bind(EXTERNAL_APPS_WORKSPACE_CLIENT)
  .toConstantValue(webExternalAppsWorkspaceClient);
container
  .bind(EXTERNAL_APPS_FOCUS_COORDINATOR)
  .toConstantValue(webExternalAppsFocusCoordinator);

// ── Task deletion (sidebar context menu / task CRUD) ──
// The task delete itself goes through the PostHog API; these clients only cover
// local-worktree cleanup (inert on web) and host UI (confirm dialog, unpin,
// navigate). TaskDeletionService is portable core.
container.load(tasksModule);
container
  .bind(TASK_DELETION_WORKSPACE_CLIENT)
  .toConstantValue(webTaskDeletionWorkspaceClient);
container.bind(TASK_DELETION_HOST).toConstantValue(webTaskDeletionHost);

// ── Shell client (chat view's useSessionCallbacks) ──
// No PTY in a browser; cloud tasks never invoke it. Bound as a stub so the
// eager useService call resolves.
container.bind(SHELL_CLIENT).toConstantValue(webShellClient);

// ── Archive (sidebar's ArchivedTasksController) ──
// The controller resolves eagerly for the sidebar; UnarchiveService needs an
// ARCHIVE_CLIENT. Its methods are user actions (unarchive/delete/context menu)
// backed by workspace-server on desktop — not available on web, so reject. The
// archived-task LIST comes from the api-client, not this client.
container.load(archiveModule);
container.bind(ARCHIVE_CLIENT).toConstantValue({
  unarchive: () =>
    Promise.reject(new Error("Unarchive is not available on the web")),
  delete: () => Promise.reject(new Error("Delete is not available on the web")),
  showArchivedTaskContextMenu: () => Promise.resolve({ action: null }),
});

// ── Updates (UpdateAvailableModal / WhatsNewModal at __root) ──
// Auto-update is a desktop (Electron) capability; a web app updates on reload.
// Report disabled/up-to-date and never emit update events.
container.bind(UPDATES_CLIENT).toConstantValue({
  install: () => Promise.resolve({ installed: false }),
  check: () => Promise.resolve({ success: true }),
  isEnabled: () => Promise.resolve({ enabled: false }),
  getStatus: () => Promise.resolve({ checking: false, upToDate: true }),
  onStatus: () => ({ unsubscribe: () => {} }),
  onReady: () => ({ unsubscribe: () => {} }),
  onCheckFromMenu: () => ({ unsubscribe: () => {} }),
});

// ── Git cache keys (git-interaction invalidation) ──
// Only a query-key/filter mapper. Web has no git/fs router or reads, so these
// keys match nothing; the adapter just produces valid tRPC-shaped keys so
// invalidation calls don't throw.
container.bind(GIT_CACHE_KEY_PROVIDER).toConstantValue(webGitCacheKeyProvider);

// ── Team skills (skills panel) ──
// Listing team skills is a real PostHog API call, so TeamSkillsService is bound
// for real. Its workspace client only does local-disk export/install (publish a
// local skill / materialize a team skill to disk) — neither exists on web, so
// those two methods reject.
container.load(skillsCoreModule);
container.bind(SKILLS_WORKSPACE_CLIENT).toConstantValue({
  exportSkill: () =>
    Promise.reject(
      new Error("Publishing a local skill is not available on the web"),
    ),
  installTeamSkill: () =>
    Promise.reject(
      new Error("Installing a skill locally is not available on the web"),
    ),
});

// ── Sessions: cloud-artifact upload + title generation ──
// CloudArtifactService (run attachment upload) is resolved during cloud task
// creation; TitleGeneratorService is resolved by the chat view. Both are
// portable core (sessionsModule). Their host clients are local-fs/skill readers
// and the title LLM call — all degrade on the cloud-only web host (see
// web-sessions-clients.ts).
container.load(sessionsModule);
container
  .bind(CLOUD_ARTIFACT_READ_FILE_AS_BASE64)
  .toConstantValue(webReadFileAsBase64);
container
  .bind(CLOUD_ARTIFACT_BUNDLE_LOCAL_SKILL)
  .toConstantValue(webBundleLocalSkill);
container
  .bind(CLOUD_ARTIFACT_RESOLVE_SKILL_DEPENDENCIES)
  .toConstantValue(webResolveSkillBundleDependencies);
container
  .bind(TITLE_GENERATOR_FILE_READ_CLIENT)
  .toConstantValue(webTitleGeneratorFileReadClient);
container
  .bind(TITLE_GENERATOR_LOGGER)
  .toConstantValue(webTitleGeneratorLogger(scoped()));
// LLM gateway (task title/summary generation, etc.). The portable core service
// runs in the browser directly — the gateway is CORS-open — over a web host
// that authenticates with AuthService and builds the same gateway URLs the
// desktop main process uses.
container.load(llmGatewayModule);
container.bind(LLM_GATEWAY_HOST).toDynamicValue((ctx) => {
  const auth = () => ctx.get<AuthService>(AUTH_SERVICE);
  return {
    getValidAccessToken: () => auth().getValidAccessToken(),
    authenticatedFetch: (url: string, init?: RequestInit) =>
      auth().authenticatedFetch(
        (input, fetchInit) => fetch(input, fetchInit),
        url,
        init,
      ),
    messagesUrl: (apiHost: string) =>
      `${getLlmGatewayUrl(apiHost)}/v1/messages`,
    usageUrl: (apiHost: string) => getGatewayUsageUrl(apiHost),
    defaultModel: DEFAULT_GATEWAY_MODEL,
  };
});

// ── Local handoff (cloud git header's "hand off to local" affordance) ──
// LocalHandoffService is resolved eagerly by CloudGitInteractionHeader. The
// dialog + notifier are host-agnostic UI (reused from @posthog/ui); the host is
// local-fs (pick a folder, add it) which can't run on the browser, so it's
// stubbed — a cloud-only host can't hand a task off to a local checkout.
container.bind(LOCAL_HANDOFF_HOST).toConstantValue({
  getRepositoryByRemoteUrl: () => Promise.resolve(null),
  selectDirectory: () => Promise.resolve(null),
  addFolder: () =>
    Promise.reject(new Error("Local handoff is not available on the web")),
});
container.bind(LOCAL_HANDOFF_DIALOG).toConstantValue(localHandoffDialog);
container.bind(LOCAL_HANDOFF_NOTIFIER).toConstantValue(localHandoffNotifier);
container
  .bind(LOCAL_HANDOFF_SERVICE)
  .to(LocalHandoffService)
  .inSingletonScope();

// ── File watcher (TaskDetail's useRepoFileWatcher) ──
// Watches a local repo for changes; there is none on web. The consumer gates
// start/stop on a repoPath (null for cloud tasks), so this no-op never runs.
container.bind(FILE_WATCHER_CLIENT).toConstantValue({
  start: () => Promise.resolve(),
  stop: () => Promise.resolve(),
});

// ── Git interaction (git header's useGitInteraction) ──
// GitInteractionService is portable core. Effects are host-agnostic UI (reused
// verbatim). The write client forwards local git ops to the host git router,
// which the web host doesn't serve — those are user actions (commit/PR) that
// reject cleanly if invoked; cloud PRs flow through the cloud API, not here.
container.load(gitInteractionModule);
container.bind(GIT_WRITE_CLIENT).toConstantValue(gitWriteClient);
container.bind(GIT_INTERACTION_EFFECTS).toConstantValue(gitInteractionEffects);

// ── Diff rendering (chat view's diff blocks + the code review page) ──
// Pure browser code (a Vite worker asset + ChangesPanel), reused verbatim from
// the desktop renderer. ChangesPanel renders cloud diffs via useCloudChangedFiles.
container.bind(DIFF_WORKER_FACTORY).toConstantValue(webDiffWorkerFactory);
container.bind(REVIEW_HOST).toConstantValue(webReviewHost);

// ── Notifications (task-completion notifications + settings test harness) ──
// Real browser implementation over the Web Notifications API. NotificationBus
// (notificationsUiModule) is resolved by SessionService on task events and by
// the settings test harness; it needs these three providers.
container.load(notificationsUiModule);
container.bind(NOTIFICATIONS_SERVICE).toConstantValue(webNotifications);
container
  .bind(NOTIFICATION_SETTINGS_PROVIDER)
  .toConstantValue(webNotificationSettings);
container.bind(ACTIVE_VIEW_PROVIDER).toConstantValue(webActiveView);

// ── Inbox: resolve the default cloud-run model from the LLM gateway ──
// Host capability consumed by UI hooks (canvas/home/inbox) that create cloud
// runs. Same logic as desktop-services.ts, over the web host router's
// getPreviewConfigOptions (backed by the CORS-open gateway, web-agent-config.ts).
const reportModelResolverLog = scoped("report-model-resolver");
container.bind(REPORT_MODEL_RESOLVER).toConstantValue({
  async resolveDefaultModel(
    apiHost: string,
    adapter: Adapter,
    preferredModel?: string | null,
  ): Promise<string | undefined> {
    try {
      const options = await hostTrpcClient.agent.getPreviewConfigOptions.query({
        apiHost,
        adapter,
      });
      return selectModelFromOptions(options, preferredModel);
    } catch (error) {
      reportModelResolverLog.warn("Failed to resolve default model", {
        error,
        adapter,
      });
      return undefined;
    }
  },
} satisfies ReportModelResolver);

// Fail loudly at composition time if a capability the shared app resolves via
// service location is unbound, instead of limping to the first navigation that
// needs it (how the missing reportModelResolver first surfaced). This runs at
// module load, so any boot — including the e2e smoke run — trips an unbound
// required capability immediately.
assertHostCapabilities(container, REQUIRED_HOST_CAPABILITIES);

setRootContainer(container);

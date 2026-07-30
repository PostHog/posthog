import type { HostRouter } from "@posthog/host-router/router";
import { additionalDirectoriesRouter } from "@posthog/host-router/routers/additional-directories.router";
import { agentRouter } from "@posthog/host-router/routers/agent.router";
import { analyticsRouter } from "@posthog/host-router/routers/analytics.router";
import { archiveRouter } from "@posthog/host-router/routers/archive.router";
import { authRouter } from "@posthog/host-router/routers/auth.router";
import { autoresearchRouter } from "@posthog/host-router/routers/autoresearch.router";
import { browserTabsRouter } from "@posthog/host-router/routers/browser-tabs.router";
import { canvasDataRouter } from "@posthog/host-router/routers/canvas-data.router";
import { canvasTemplatesRouter } from "@posthog/host-router/routers/canvas-templates.router";
import { channelTasksRouter } from "@posthog/host-router/routers/channel-tasks.router";
import { claudeCliSessionsRouter } from "@posthog/host-router/routers/claude-cli-sessions.router";
import { cloudTaskRouter } from "@posthog/host-router/routers/cloud-task.router";
import { connectivityRouter } from "@posthog/host-router/routers/connectivity.router";
import { contextMenuRouter } from "@posthog/host-router/routers/context-menu.router";
import { dashboardsRouter } from "@posthog/host-router/routers/dashboards.router";
import { deepLinkRouter } from "@posthog/host-router/routers/deep-link.router";
import { enrichmentRouter } from "@posthog/host-router/routers/enrichment.router";
import { environmentRouter } from "@posthog/host-router/routers/environment.router";
import { externalAppsRouter } from "@posthog/host-router/routers/external-apps.router";
import { fileWatcherRouter } from "@posthog/host-router/routers/file-watcher.router";
import { focusRouter } from "@posthog/host-router/routers/focus.router";
import { foldersRouter } from "@posthog/host-router/routers/folders.router";
import { fsRouter } from "@posthog/host-router/routers/fs.router";
import { gitRouter } from "@posthog/host-router/routers/git.router";
import { githubIntegrationRouter } from "@posthog/host-router/routers/github-integration.router";
import { handoffRouter } from "@posthog/host-router/routers/handoff.router";
import { integrationRouter } from "@posthog/host-router/routers/integration.router";
import { linearIntegrationRouter } from "@posthog/host-router/routers/linear-integration.router";
import { llmGatewayRouter } from "@posthog/host-router/routers/llm-gateway.router";
import { localMcpRouter } from "@posthog/host-router/routers/local-mcp.router";
import { logsRouter } from "@posthog/host-router/routers/logs.router";
import { mcpAppsRouter } from "@posthog/host-router/routers/mcp-apps.router";
import { mcpCallbackRouter } from "@posthog/host-router/routers/mcp-callback.router";
import { mcpRelayRouter } from "@posthog/host-router/routers/mcp-relay.router";
import { notificationRouter } from "@posthog/host-router/routers/notification.router";
import { oauthRouter } from "@posthog/host-router/routers/oauth.router";
import { onboardingImportRouter } from "@posthog/host-router/routers/onboarding-import.router";
import { osRouter } from "@posthog/host-router/routers/os.router";
import { piSessionRouter } from "@posthog/host-router/routers/pi-session.router";
import { processTrackingRouter } from "@posthog/host-router/routers/process-tracking.router";
import { provisioningRouter } from "@posthog/host-router/routers/provisioning.router";
import { releaseFeedRouter } from "@posthog/host-router/routers/release-feed.router";
import { secureStoreRouter } from "@posthog/host-router/routers/secure-store.router";
import { shellRouter } from "@posthog/host-router/routers/shell.router";
import { skillsRouter } from "@posthog/host-router/routers/skills.router";
import { slackIntegrationRouter } from "@posthog/host-router/routers/slack-integration.router";
import { sleepRouter } from "@posthog/host-router/routers/sleep.router";
import { speechRouter } from "@posthog/host-router/routers/speech.router";
import { suspensionRouter } from "@posthog/host-router/routers/suspension.router";
import { uiRouter } from "@posthog/host-router/routers/ui.router";
import { updatesRouter } from "@posthog/host-router/routers/updates.router";
import { usageMonitorRouter } from "@posthog/host-router/routers/usage-monitor.router";
import { workspaceRouter } from "@posthog/host-router/routers/workspace.router";
import { devRouter } from "./routers/dev";
import { discordPresenceRouter } from "./routers/discord-presence";
import { encryptionRouter } from "./routers/encryption";
import { workspaceServerRouter } from "./routers/workspace-server";
import { router } from "./trpc";

export const trpcRouter = router({
  additionalDirectories: additionalDirectoriesRouter,
  agent: agentRouter,
  analytics: analyticsRouter,
  archive: archiveRouter,
  auth: authRouter,
  autoresearch: autoresearchRouter,
  browserTabs: browserTabsRouter,
  canvasData: canvasDataRouter,
  canvasTemplates: canvasTemplatesRouter,
  channelTasks: channelTasksRouter,
  claudeCliSessions: claudeCliSessionsRouter,
  dashboards: dashboardsRouter,
  cloudTask: cloudTaskRouter,
  connectivity: connectivityRouter,
  contextMenu: contextMenuRouter,
  dev: devRouter,
  discordPresence: discordPresenceRouter,
  enrichment: enrichmentRouter,
  environment: environmentRouter,
  encryption: encryptionRouter,
  externalApps: externalAppsRouter,
  fileWatcher: fileWatcherRouter,
  focus: focusRouter,
  folders: foldersRouter,
  fs: fsRouter,
  git: gitRouter,
  githubIntegration: githubIntegrationRouter,
  releaseFeed: releaseFeedRouter,
  handoff: handoffRouter,
  integration: integrationRouter,
  linearIntegration: linearIntegrationRouter,
  llmGateway: llmGatewayRouter,
  localMcp: localMcpRouter,
  mcpApps: mcpAppsRouter,
  mcpCallback: mcpCallbackRouter,
  mcpRelay: mcpRelayRouter,
  notification: notificationRouter,
  oauth: oauthRouter,
  onboardingImport: onboardingImportRouter,
  logs: logsRouter,
  os: osRouter,
  piSession: piSessionRouter,
  processTracking: processTrackingRouter,
  provisioning: provisioningRouter,
  sleep: sleepRouter,
  suspension: suspensionRouter,
  secureStore: secureStoreRouter,
  shell: shellRouter,
  speech: speechRouter,
  skills: skillsRouter,
  slackIntegration: slackIntegrationRouter,
  ui: uiRouter,
  updates: updatesRouter,
  usageMonitor: usageMonitorRouter,
  deepLink: deepLinkRouter,
  workspace: workspaceRouter,
  workspaceServer: workspaceServerRouter,
});

export type TrpcRouter = typeof trpcRouter;

/**
 * The renderer and @posthog/ui are typed against HostRouter, so every route it
 * declares must actually be served by this assembly — a route present in the
 * type but missing here fails only at runtime with NOT_FOUND (#2442 dropped
 * onboardingImport this way, silently breaking the onboarding import step).
 * When this assignment errors, its expected type names the missing routes.
 */
type MissingHostRoutes = Exclude<keyof HostRouter, keyof TrpcRouter>;
export const servesEveryHostRoute: [MissingHostRoutes] extends [never]
  ? true
  : MissingHostRoutes = true;

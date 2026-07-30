/**
 * Main process DI tokens.
 *
 * IMPORTANT: These tokens are for main process only.
 * Never import this file from renderer code.
 */

// Workspace-server connection (typed client over the ELECTRON_RUN_AS_NODE child)
export const WORKSPACE_CLIENT = Symbol.for(
  "posthog.host.main.workspace.client",
);

// Stores
export const SETTINGS_STORE = Symbol.for("posthog.host.main.settings.store");
export const SECURE_STORE_SERVICE = Symbol.for(
  "posthog.host.main.secure-store.service",
);
export const SECURE_STORE_BACKEND = Symbol.for(
  "posthog.host.main.secure-store.backend",
);
export const ENCRYPTION_SERVICE = Symbol.for(
  "posthog.host.main.encryption.service",
);

// Database
export const AUTH_PREFERENCE_REPOSITORY = Symbol.for(
  "posthog.host.main.auth.preference-repository",
);
export const DATABASE_SERVICE = Symbol.for(
  "posthog.host.main.database.service",
);
export const AUTH_SESSION_REPOSITORY = Symbol.for(
  "posthog.host.main.auth.session-repository",
);
export const REPOSITORY_REPOSITORY = Symbol.for(
  "posthog.host.main.repository.repository",
);
export const WORKSPACE_REPOSITORY = Symbol.for(
  "posthog.host.main.workspace.repository",
);
export const WORKTREE_REPOSITORY = Symbol.for(
  "posthog.host.main.worktree.repository",
);
export const ARCHIVE_REPOSITORY = Symbol.for(
  "posthog.host.main.archive.repository",
);
export const SUSPENSION_REPOSITORY = Symbol.for(
  "posthog.host.main.suspension.repository",
);
export const DEFAULT_ADDITIONAL_DIRECTORY_REPOSITORY = Symbol.for(
  "posthog.host.main.additional-directory.default-repository",
);

// Services
export const AUTH_SERVICE = Symbol.for("posthog.host.main.auth.service");
export const SUSPENSION_SERVICE = Symbol.for(
  "posthog.host.main.suspension.service",
);
export const APP_LIFECYCLE_SERVICE = Symbol.for(
  "posthog.host.main.app-lifecycle.service",
);
export const CLOUD_TASK_SERVICE = Symbol.for(
  "posthog.host.main.cloud-task.service",
);
export const CONTEXT_MENU_SERVICE = Symbol.for(
  "posthog.host.main.context-menu.service",
);

export const EXTERNAL_APPS_SERVICE = Symbol.for(
  "posthog.host.main.external-apps.service",
);
export const LLM_GATEWAY_SERVICE = Symbol.for(
  "posthog.host.main.llm-gateway.service",
);
export const MCP_APPS_SERVICE = Symbol.for(
  "posthog.host.main.mcp-apps.service",
);
export const FILE_WATCHER_SERVICE = Symbol.for(
  "posthog.host.main.file-watcher.service",
);
export const FS_SERVICE = Symbol.for("posthog.host.main.fs.service");
export const GIT_SERVICE = Symbol.for("posthog.host.main.git.service");
export const DEEP_LINK_SERVICE = Symbol.for(
  "posthog.host.main.deep-link.service",
);
export const PROCESS_TRACKING_SERVICE = Symbol.for(
  "posthog.host.main.process-tracking.service",
);
export const SLEEP_SERVICE = Symbol.for("posthog.host.main.sleep.service");
export const POSTHOG_PLUGIN_SERVICE = Symbol.for(
  "posthog.host.main.posthog-plugin.service",
);
export const UPDATES_SERVICE = Symbol.for("posthog.host.main.updates.service");
export const TASK_LINK_SERVICE = Symbol.for(
  "posthog.host.main.task-link.service",
);
export const INBOX_LINK_SERVICE = Symbol.for(
  "posthog.host.main.inbox-link.service",
);
export const SCOUT_LINK_SERVICE = Symbol.for(
  "posthog.host.main.scout-link.service",
);
export const NEW_TASK_LINK_SERVICE = Symbol.for(
  "posthog.host.main.new-task-link.service",
);
export const APPROVAL_LINK_SERVICE = Symbol.for(
  "posthog.host.main.approval-link.service",
);
export const OPEN_TARGET_LINK_SERVICE = Symbol.for(
  "posthog.host.main.open-target-link.service",
);
export const CANVAS_LINK_SERVICE = Symbol.for(
  "posthog.host.main.canvas-link.service",
);
export const CHANNEL_LINK_SERVICE = Symbol.for(
  "posthog.host.main.channel-link.service",
);
export const WATCHER_REGISTRY_SERVICE = Symbol.for(
  "posthog.host.main.watcher-registry.service",
);
export const PROVISIONING_SERVICE = Symbol.for(
  "posthog.host.main.provisioning.service",
);
export const WORKSPACE_SERVICE = Symbol.for(
  "posthog.host.main.workspace.service",
);
export const WORKSPACE_SERVER_SERVICE = Symbol.for(
  "posthog.host.main.workspace-server.service",
);
export const DISCORD_PRESENCE_SERVICE = Symbol.for(
  "posthog.host.main.discord-presence.service",
);
export const DEV_FLAGS_SERVICE = Symbol.for(
  "posthog.host.main.dev-flags.service",
);
export const DEV_METRICS_SERVICE = Symbol.for(
  "posthog.host.main.dev-metrics.service",
);
export const DEV_NETWORK_SERVICE = Symbol.for(
  "posthog.host.main.dev-network.service",
);
export const DEV_LOGS_SERVICE = Symbol.for(
  "posthog.host.main.dev-logs.service",
);
export const DEV_ACTIONS_SERVICE = Symbol.for(
  "posthog.host.main.dev-actions.service",
);

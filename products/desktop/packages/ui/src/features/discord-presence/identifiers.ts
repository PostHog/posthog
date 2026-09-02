/**
 * UI-side port for the Discord Rich Presence integration. The connection,
 * reconnection, rate-limiting, and privacy-aware formatting all live in the
 * host service (`apps/code` main process); this port is the thin, host-neutral
 * surface the renderer talks to. The desktop host binds a tRPC-backed adapter.
 */

/** Snapshot of the presence integration, surfaced to the settings UI. */
export interface DiscordPresenceState {
  /** Whether the user has turned the integration on. */
  enabled: boolean;
  /** Whether a live socket to the Discord client is currently established. */
  connected: boolean;
  /** Whether a Discord application id is configured (false = dev placeholder). */
  configured: boolean;
  /** Privacy toggle: include the focused task's title in the presence. */
  showTaskTitle: boolean;
  /** Privacy toggle: include the repository name in the presence. */
  showRepoName: boolean;
}

/**
 * High-level description of what the user is doing, pushed from the renderer
 * (which owns navigation/session UI state). The host service decides how — and
 * whether, given the privacy toggles — to render it onto Discord.
 */
export interface PresenceIntent {
  /** True when a task is open in the foreground. */
  hasActiveTask: boolean;
  /** Title of the focused task, or null when none/hidden upstream. */
  taskTitle: string | null;
  /** "org/repo" of the focused task, or null. */
  repoName: string | null;
  /** True while the agent is actively working on the focused task. */
  agentRunning: boolean;
}

export interface DiscordPresenceClient {
  getState(): Promise<DiscordPresenceState>;
  setEnabled(enabled: boolean): Promise<void>;
  setShowTaskTitle(value: boolean): Promise<void>;
  setShowRepoName(value: boolean): Promise<void>;
  /** Feed the host the latest high-level intent (rate-limited host-side). */
  setActivity(intent: PresenceIntent): Promise<void>;
  /** Observe live status changes; returns an unsubscribe function. */
  onStatusChanged(onData: (state: DiscordPresenceState) => void): () => void;
}

export const DISCORD_PRESENCE_CLIENT = Symbol.for(
  "posthog.ui.discord-presence.client",
);

import { z } from "zod";

/** Snapshot of the presence integration, surfaced to the settings UI. */
export const discordPresenceStateSchema = z.object({
  /** Whether the user has turned the integration on. */
  enabled: z.boolean(),
  /** Whether a live socket to the Discord client is currently established. */
  connected: z.boolean(),
  /** Whether a Discord application id is configured (false = dev placeholder). */
  configured: z.boolean(),
  /** Privacy toggle: include the focused task's title in the presence. */
  showTaskTitle: z.boolean(),
  /** Privacy toggle: include the repository name in the presence. */
  showRepoName: z.boolean(),
});

export type DiscordPresenceState = z.infer<typeof discordPresenceStateSchema>;

/**
 * High-level description of what the user is doing, pushed from the renderer
 * (which owns navigation/session UI state). The service decides how — and
 * whether, given the privacy toggles — to render it onto Discord.
 */
export const presenceIntentSchema = z.object({
  /** True when a task is open in the foreground. */
  hasActiveTask: z.boolean(),
  /** Title of the focused task, or null when none/hidden upstream. */
  taskTitle: z.string().nullable(),
  /** "org/repo" of the focused task, or null. */
  repoName: z.string().nullable(),
  /** True while the agent is actively working on the focused task. */
  agentRunning: z.boolean(),
});

export type PresenceIntent = z.infer<typeof presenceIntentSchema>;

export const DiscordPresenceServiceEvent = {
  StatusChanged: "status-changed",
} as const;

export interface DiscordPresenceServiceEvents {
  [DiscordPresenceServiceEvent.StatusChanged]: DiscordPresenceState;
}

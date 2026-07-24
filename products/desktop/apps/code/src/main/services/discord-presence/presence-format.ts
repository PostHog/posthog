import {
  LARGE_IMAGE_KEY,
  MAX_FIELD_LENGTH,
  SMALL_IMAGE_IDLE,
  SMALL_IMAGE_RUNNING,
} from "./constants";
import type { DiscordActivity } from "./discord-ipc";
import type { PresenceIntent } from "./schemas";

export interface PresenceFormatOptions {
  showTaskTitle: boolean;
  showRepoName: boolean;
  /** Epoch ms used for the "elapsed" timer shown on the profile. */
  startedAt: number;
}

/**
 * Turn a high-level {@link PresenceIntent} into a Discord activity payload,
 * honouring the privacy toggles. Pure so it can be unit-tested in isolation
 * from the socket lifecycle.
 */
export function buildActivity(
  intent: PresenceIntent,
  options: PresenceFormatOptions,
): DiscordActivity {
  const { hasActiveTask, taskTitle, repoName, agentRunning } = intent;
  const { showTaskTitle, showRepoName, startedAt } = options;

  const details = truncate(
    hasActiveTask
      ? showTaskTitle && taskTitle
        ? `Working on "${taskTitle}"`
        : "Working on a task"
      : "Idle",
  );

  const statusPart = agentRunning
    ? "agent running"
    : hasActiveTask
      ? "reviewing"
      : "browsing";
  const repoPart = showRepoName && repoName ? repoName : null;
  const state = truncate(repoPart ? `${repoPart} · ${statusPart}` : statusPart);

  const smallText = agentRunning
    ? "Agent running"
    : hasActiveTask
      ? "Reviewing"
      : "Idle";

  return {
    details,
    state,
    timestamps: { start: startedAt },
    assets: {
      large_image: LARGE_IMAGE_KEY,
      large_text: "PostHog",
      small_image: agentRunning ? SMALL_IMAGE_RUNNING : SMALL_IMAGE_IDLE,
      small_text: smallText,
    },
    instance: false,
  };
}

function truncate(value: string): string {
  if (value.length <= MAX_FIELD_LENGTH) return value;
  return `${value.slice(0, MAX_FIELD_LENGTH - 1)}…`;
}

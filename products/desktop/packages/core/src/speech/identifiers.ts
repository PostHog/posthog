/** Why the agent is speaking; drives priority, greeting, and per-kind gating. */
export type SpeechKind = "needs_input" | "done" | "progress";

/**
 * Who authored the line: the agent's intentional `speak` tool call, or the
 * deterministic backstop fired by turn-complete / permission events. Backstop
 * lines are suppressed while the user is viewing the task; agent lines are not.
 */
export type SpeechSource = "agent" | "backstop";

/** A narration request as it arrives from the agent's `speak` tool call. */
export interface SpeechRequest {
  /** The message body the agent produced (no task prefix, no user name). */
  text: string;
  /** Canonical task title, prepended by the app so the user knows who's talking. */
  taskTitle: string;
  taskId?: string;
  /** True when the line is a request for the user; prioritized and never dropped. */
  needsUser?: boolean;
  /** Prepend "Hey <name>," — only for agent-authored lines, not the backstop. */
  addressByName?: boolean;
}

/** Serializes agent narration into one-at-a-time speech. */
export interface ISpeechQueue {
  enqueue(request: SpeechRequest): void;
}

export const SPEECH_QUEUE_SERVICE = Symbol.for("posthog.speech.queue");

/** Reads the user's spoken-narration settings at speak time. */
export interface SpeechSettingsProvider {
  get(): { enabled: boolean; voiceId?: string };
}

export const SPEECH_SETTINGS_PROVIDER = Symbol.for(
  "posthog.speech.settingsProvider",
);

/** Supplies the signed-in user's display name for "Hey <name>" lines. */
export interface UserNameProvider {
  /** The user's first name, or undefined when unknown (e.g. only an email). */
  getFirstName(): string | undefined;
}

export const SPEECH_USER_NAME_PROVIDER = Symbol.for(
  "posthog.speech.userNameProvider",
);

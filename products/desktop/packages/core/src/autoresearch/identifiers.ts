export const AUTORESEARCH_SERVICE = Symbol.for(
  "posthog.core.autoresearch.service",
);

/**
 * Narrow host seam onto a task's agent session. Bound by hosts to forward
 * into their session service.
 */
export interface AutoresearchSessionClient {
  /** Resolves when the turn ends, with the agent's stop reason. */
  sendPrompt(taskId: string, prompt: string): Promise<{ stopReason: string }>;
  /**
   * Reconnect the task's agent session after an error, idle-kill, or app
   * restart. Rejects when the session cannot be re-established yet.
   */
  reconnect(taskId: string): Promise<void>;
  /** Switch the session's model (stage models in split runs). */
  setModel(taskId: string, model: string): Promise<void>;
  /** Switch the session's reasoning-effort level (stage efforts in split runs). */
  setEffort(taskId: string, effort: string): Promise<void>;
}

export const AUTORESEARCH_SESSION_CLIENT = Symbol.for(
  "posthog.core.autoresearch.sessionClient",
);

/** A run as persisted by the host: an opaque JSON blob plus index columns. */
export interface StoredAutoresearchRun {
  id: string;
  taskId: string;
  /** ISO timestamp when the run reached a terminal status; null while open. */
  endedAt: string | null;
  /** JSON-serialized AutoresearchRun. */
  data: string;
}

/**
 * Narrow host seam for persisting runs across app restarts. Bound by hosts
 * that have durable storage; unbound hosts simply lose runs on reload.
 */
export interface AutoresearchStorageClient {
  save(run: StoredAutoresearchRun): Promise<void>;
  /** Runs not yet terminal. These are worth resuming after a restart. */
  listOpen(): Promise<StoredAutoresearchRun[]>;
  listByTask(taskId: string): Promise<StoredAutoresearchRun[]>;
}

export const AUTORESEARCH_STORAGE_CLIENT = Symbol.for(
  "posthog.core.autoresearch.storageClient",
);

/**
 * Availability gate, bound by hosts to their feature-flag system. Resolves
 * once flag state is known; a disabled gate stops the boot-time restore of
 * persisted runs, so the feature stays fully dormant for ungated users.
 */
export interface AutoresearchGate {
  isEnabled(): Promise<boolean>;
}

export const AUTORESEARCH_GATE = Symbol.for("posthog.core.autoresearch.gate");

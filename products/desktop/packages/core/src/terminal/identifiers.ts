export interface ShellProcessReader {
  getProcess(input: { sessionId: string }): Promise<string | null>;
}

export const SHELL_PROCESS_READER = Symbol.for(
  "posthog.core.terminal.shellProcessReader",
);

export const SHELL_PROCESS_POLLER = Symbol.for(
  "posthog.core.terminal.shellProcessPoller",
);

export const SHELL_PROCESS_POLL_INTERVAL_MS = 500;

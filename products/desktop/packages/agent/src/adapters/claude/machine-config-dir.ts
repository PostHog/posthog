/**
 * Env var the desktop app sets to the Claude config dir the machine's own
 * Claude Code CLI uses. Unset means the CLI default (`~/.claude`).
 */
export const MACHINE_CLAUDE_CONFIG_DIR_ENV =
  "POSTHOG_CODE_MACHINE_CLAUDE_CONFIG_DIR";

/**
 * Point a spawn env at the machine's own Claude config dir.
 *
 * The desktop app keeps its Claude state in an app-private `CLAUDE_CONFIG_DIR`.
 * A `claude` login made in a terminal lives in the machine's config dir, and
 * Claude Code resolves credentials from whichever dir it is pointed at, so
 * own-subscription mode must undo the app override. Only local and worktree
 * sessions reach this; cloud sessions always keep gateway auth.
 */
export function applyMachineClaudeConfigDir(env: NodeJS.ProcessEnv): void {
  const machineDir = env[MACHINE_CLAUDE_CONFIG_DIR_ENV];
  if (machineDir) {
    env.CLAUDE_CONFIG_DIR = machineDir;
  } else {
    delete env.CLAUDE_CONFIG_DIR;
  }
  delete env[MACHINE_CLAUDE_CONFIG_DIR_ENV];
}

/**
 * Credential variables that outrank the machine login in Claude Code's auth
 * precedence. Every `claude` invocation that must see the machine login drops
 * them, ambient shell values included.
 */
export const MACHINE_AUTH_STRIPPED_KEYS = [
  "ANTHROPIC_BASE_URL",
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_CUSTOM_HEADERS",
] as const;

/**
 * The same env change as {@link applyMachineClaudeConfigDir}, as set and unset
 * lists. Terminals build their env from a shell template rather than from a
 * copy of `process.env`, so they cannot use the mutating form.
 */
export function machineClaudeAuthEnv(env: NodeJS.ProcessEnv = process.env): {
  set: Record<string, string>;
  unset: string[];
} {
  const machineDir = env[MACHINE_CLAUDE_CONFIG_DIR_ENV];
  const unset = [
    ...MACHINE_AUTH_STRIPPED_KEYS,
    MACHINE_CLAUDE_CONFIG_DIR_ENV,
  ] as string[];
  if (machineDir) {
    return { set: { CLAUDE_CONFIG_DIR: machineDir }, unset };
  }
  return { set: {}, unset: [...unset, "CLAUDE_CONFIG_DIR"] };
}

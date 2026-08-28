export const MACHINE_CLAUDE_CONFIG_DIR_ENV =
  "POSTHOG_CODE_MACHINE_CLAUDE_CONFIG_DIR";

export function applyMachineClaudeConfigDir(env: NodeJS.ProcessEnv): void {
  const machineDir = env[MACHINE_CLAUDE_CONFIG_DIR_ENV];
  if (machineDir) {
    env.CLAUDE_CONFIG_DIR = machineDir;
  } else {
    delete env.CLAUDE_CONFIG_DIR;
  }
  delete env[MACHINE_CLAUDE_CONFIG_DIR_ENV];
}

export const MACHINE_AUTH_STRIPPED_KEYS = [
  "ANTHROPIC_BASE_URL",
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_CUSTOM_HEADERS",
] as const;

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

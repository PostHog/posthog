import * as os from "node:os";
import * as path from "node:path";

export interface MachineClaudeAuth {
  configDir?: string;
}

export const MACHINE_AUTH_STRIPPED_KEYS = [
  "ANTHROPIC_BASE_URL",
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_CUSTOM_HEADERS",
  "OPENAI_BASE_URL",
  "OPENAI_API_KEY",
  "CLAUDE_CODE_USE_BEDROCK",
  "CLAUDE_CODE_USE_VERTEX",
  "CLAUDE_CODE_USE_FOUNDRY",
  "CLAUDE_CODE_USE_ANTHROPIC_AWS",
  "CLAUDE_CODE_USE_MANTLE",
  "CLAUDE_CODE_ENABLE_TELEMETRY",
  "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA",
  "CLAUDE_CODE_PROPAGATE_TRACEPARENT",
  "OTEL_TRACES_EXPORTER",
  "OTEL_EXPORTER_OTLP_PROTOCOL",
  "OTEL_EXPORTER_OTLP_ENDPOINT",
  "TRACEPARENT",
  "TRACESTATE",
] as const;

let resolvedMachineAuth: MachineClaudeAuth = {};

export function setMachineClaudeConfigDir(configDir: string | undefined): void {
  resolvedMachineAuth = configDir ? { configDir } : {};
}

export function machineClaudeAuth(): MachineClaudeAuth {
  return resolvedMachineAuth;
}

export function applyMachineClaudeAuth(
  env: Record<string, string | undefined>,
  auth: MachineClaudeAuth,
): void {
  for (const key of MACHINE_AUTH_STRIPPED_KEYS) {
    delete env[key];
  }
  if (auth.configDir) {
    env.CLAUDE_CONFIG_DIR = auth.configDir;
  } else {
    env.CLAUDE_CONFIG_DIR = path.join(os.homedir(), ".claude");
  }
}

export function machineClaudeAuthShellEnv(auth: MachineClaudeAuth): {
  set: Record<string, string>;
  unset: string[];
} {
  const unset: string[] = [...MACHINE_AUTH_STRIPPED_KEYS];
  if (auth.configDir) {
    return { set: { CLAUDE_CONFIG_DIR: auth.configDir }, unset };
  }
  return {
    set: { CLAUDE_CONFIG_DIR: path.join(os.homedir(), ".claude") },
    unset,
  };
}

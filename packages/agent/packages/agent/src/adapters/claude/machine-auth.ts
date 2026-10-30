import * as os from "node:os";
import * as path from "node:path";

export interface MachineClaudeAuth {
  configDir?: string;
  oauthToken?: string;
  // Leave CLAUDE_CONFIG_DIR as the user has it: the CLI keeps a separate Keychain login per explicit dir, so pinning
  // even the default path hides the login a plain `claude auth login` made.
  keepUserConfigDir?: boolean;
}

/** Keys that pick the CLI's provider or its endpoint without ANTHROPIC_BASE_URL. */
export const CLAUDE_PROVIDER_ENV_KEYS = [
  "CLAUDE_CODE_USE_BEDROCK",
  "CLAUDE_CODE_USE_VERTEX",
  "CLAUDE_CODE_USE_FOUNDRY",
  "CLAUDE_CODE_USE_ANTHROPIC_AWS",
  "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
  "CLAUDE_CODE_USE_MANTLE",
  "CLAUDE_CODE_USE_GATEWAY",
  "ANTHROPIC_BEDROCK_BASE_URL",
  "ANTHROPIC_BEDROCK_MANTLE_BASE_URL",
  "ANTHROPIC_AWS_BASE_URL",
  "ANTHROPIC_VERTEX_BASE_URL",
  "ANTHROPIC_GOOGLE_CLOUD_BASE_URL",
  "ANTHROPIC_FOUNDRY_BASE_URL",
  "AWS_ENDPOINT_URL",
  "AWS_ENDPOINT_URL_BEDROCK",
  "AWS_ENDPOINT_URL_BEDROCK_RUNTIME",
] as const;

/** Keys that route the CLI's connections through another socket or proxy. */
export const CLAUDE_TRANSPORT_ENV_KEYS = [
  "ANTHROPIC_UNIX_SOCKET",
  "HTTP_PROXY",
  "HTTPS_PROXY",
  "ALL_PROXY",
  "http_proxy",
  "https_proxy",
  "all_proxy",
] as const;

export const MACHINE_AUTH_STRIPPED_KEYS = [
  "ANTHROPIC_BASE_URL",
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_API_KEY",
  "ANTHROPIC_CUSTOM_HEADERS",
  "OPENAI_BASE_URL",
  "OPENAI_API_KEY",
  ...CLAUDE_PROVIDER_ENV_KEYS,
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

export const CLOUD_AUTH_STRIPPED_KEYS = [
  ...CLAUDE_TRANSPORT_ENV_KEYS,
  "CLAUDE_CODE_EXECUTABLE",
  "NODE_EXTRA_CA_CERTS",
  "SSL_CERT_FILE",
  "SSL_CERT_DIR",
  "NODE_OPTIONS",
] as const;

export function setMachineClaudeConfigDir(configDir: string | undefined): void {
  resolvedMachineAuth = configDir ? { configDir } : {};
}

export function keepUserClaudeConfigDir(): void {
  resolvedMachineAuth = { keepUserConfigDir: true };
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
  if (auth.oauthToken) {
    for (const key of CLOUD_AUTH_STRIPPED_KEYS) delete env[key];
    env.NODE_TLS_REJECT_UNAUTHORIZED = "1";
    delete env.CLAUDE_CODE_OAUTH_TOKEN;
    delete env.CLAUDE_CODE_REMOTE;
    env.CLAUDE_CODE_SUBPROCESS_ENV_SCRUB = "0";
  }
  if (auth.configDir) {
    env.CLAUDE_CONFIG_DIR = auth.configDir;
  } else if (!auth.keepUserConfigDir) {
    env.CLAUDE_CONFIG_DIR = path.join(os.homedir(), ".claude");
  }
}

export function machineClaudeAuthShellEnv(auth: MachineClaudeAuth): {
  set: Record<string, string>;
  unset: string[];
} {
  const unset: string[] = [
    ...MACHINE_AUTH_STRIPPED_KEYS,
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
  ];
  if (auth.configDir) {
    return { set: { CLAUDE_CONFIG_DIR: auth.configDir }, unset };
  }
  return {
    set: { CLAUDE_CONFIG_DIR: path.join(os.homedir(), ".claude") },
    unset,
  };
}

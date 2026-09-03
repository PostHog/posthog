import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { POSTHOG_NOTIFICATIONS } from "../acp-extensions";
import { resolveRtkPrefix } from "../adapters/claude/session/rtk";

const execFileAsync = promisify(execFile);

export interface RtkSavingsSummary {
  totalCommands: number;
  inputTokens: number;
  outputTokens: number;
  tokensSaved: number;
}

interface ResolveRtkSavingsOptions {
  env?: NodeJS.ProcessEnv;
  resolveBinary?: (env: NodeJS.ProcessEnv) => string | undefined;
  runGain?: (binary: string, env: NodeJS.ProcessEnv) => Promise<string>;
}

function toFiniteNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function parseGainSummary(stdout: string): RtkSavingsSummary | null {
  const parsed: unknown = JSON.parse(stdout);
  if (!parsed || typeof parsed !== "object") return null;
  const summary = (parsed as { summary?: Record<string, unknown> }).summary;
  if (!summary || typeof summary !== "object") return null;

  return {
    totalCommands: toFiniteNumber(summary.total_commands),
    inputTokens: toFiniteNumber(summary.total_input),
    outputTokens: toFiniteNumber(summary.total_output),
    tokensSaved: toFiniteNumber(summary.total_saved),
  };
}

async function defaultRunGain(
  binary: string,
  env: NodeJS.ProcessEnv,
): Promise<string> {
  const { stdout } = await execFileAsync(binary, ["gain", "--format", "json"], {
    timeout: 5_000,
    maxBuffer: 10 * 1024 * 1024,
    env: scrubbedGainEnv(env),
  });
  return stdout;
}

const GAIN_ENV_ALLOWLIST = [
  "PATH",
  "HOME",
  "USERPROFILE",
  "APPDATA",
  "LOCALAPPDATA",
  "XDG_CONFIG_HOME",
  "XDG_DATA_HOME",
  "TMPDIR",
  "TEMP",
  "TMP",
  "SystemRoot",
  "RTK_DB_PATH",
];

export function scrubbedGainEnv(env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return Object.fromEntries(
    GAIN_ENV_ALLOWLIST.filter((key) => env[key] !== undefined).map((key) => [
      key,
      env[key],
    ]),
  );
}

export interface RtkSavingsNotificationOptions {
  taskId: string;
  runId: string;
  teamId: number;
  runtimeAdapter?: string;
  model?: string;
  resolveSavings?: () => Promise<RtkSavingsSummary | null>;
}

export async function createRtkSavingsNotification({
  taskId,
  runId,
  teamId,
  runtimeAdapter,
  model,
  resolveSavings = resolveRtkSavings,
}: RtkSavingsNotificationOptions): Promise<{
  type: "notification";
  timestamp: string;
  notification: {
    jsonrpc: "2.0";
    method: typeof POSTHOG_NOTIFICATIONS.RTK_SAVINGS;
    params: {
      task_id: string;
      run_id: string;
      team_id: number;
      counter_id: string;
      cumulative_commands: number;
      cumulative_input_tokens: number;
      cumulative_output_tokens: number;
      cumulative_tokens_saved: number;
      runtime_adapter?: string;
      model?: string;
    };
  };
} | null> {
  const savings = await resolveSavings();
  if (!savings) {
    return null;
  }

  return {
    type: "notification",
    timestamp: new Date().toISOString(),
    notification: {
      jsonrpc: "2.0",
      method: POSTHOG_NOTIFICATIONS.RTK_SAVINGS,
      params: {
        task_id: taskId,
        run_id: runId,
        team_id: teamId,
        counter_id: taskId,
        cumulative_commands: savings.totalCommands,
        cumulative_input_tokens: savings.inputTokens,
        cumulative_output_tokens: savings.outputTokens,
        cumulative_tokens_saved: savings.tokensSaved,
        runtime_adapter: runtimeAdapter,
        model,
      },
    },
  };
}

export async function resolveRtkSavings({
  env = process.env,
  resolveBinary = resolveRtkPrefix,
  runGain = defaultRunGain,
}: ResolveRtkSavingsOptions = {}): Promise<RtkSavingsSummary | null> {
  const binary = resolveBinary(env);
  if (!binary) return null;

  try {
    const summary = parseGainSummary(await runGain(binary, env));
    return summary && summary.totalCommands > 0 ? summary : null;
  } catch {
    return null;
  }
}

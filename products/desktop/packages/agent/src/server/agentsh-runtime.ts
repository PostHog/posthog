import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";
import type { Logger } from "../utils/logger";

export const AGENTSH_SESSION_ID_FILE = "/tmp/agentsh-session-id";

const execFileAsync = promisify(execFile);

interface AgentshVersionOutput {
  stdout: string;
  stderr: string;
}

interface ResolveAgentshRuntimeInfoOptions {
  sessionIdPath?: string;
  readSessionId?: (path: string) => Promise<string>;
  getVersion?: () => Promise<AgentshVersionOutput>;
}

export interface AgentshRuntimeInfo {
  sessionId: string;
  version: string | null;
  versionLookupError?: string;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function parseAgentshVersion(output: AgentshVersionOutput): string | null {
  const version = `${output.stdout}\n${output.stderr}`
    .split("\n")
    .map((line) => line.trim())
    .find(Boolean);
  return version ?? null;
}

async function getAgentshVersion(): Promise<AgentshVersionOutput> {
  const { stdout, stderr } = await execFileAsync("agentsh", ["--version"], {
    timeout: 5_000,
  });
  return { stdout, stderr };
}

export async function resolveAgentshRuntimeInfo({
  sessionIdPath = AGENTSH_SESSION_ID_FILE,
  readSessionId = async (path: string) => readFile(path, "utf8"),
  getVersion = getAgentshVersion,
}: ResolveAgentshRuntimeInfoOptions = {}): Promise<AgentshRuntimeInfo | null> {
  let sessionId: string;
  try {
    sessionId = (await readSessionId(sessionIdPath)).trim();
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code === "ENOENT") {
      return null;
    }
    throw error;
  }

  if (!sessionId) {
    return null;
  }

  try {
    const output = await getVersion();
    return {
      sessionId,
      version: parseAgentshVersion(output),
    };
  } catch (error) {
    return {
      sessionId,
      version: null,
      versionLookupError: errorMessage(error),
    };
  }
}

export async function logAgentshRuntimeInfo(
  logger: Pick<Logger, "debug">,
  options?: ResolveAgentshRuntimeInfoOptions,
): Promise<void> {
  const agentsh = await resolveAgentshRuntimeInfo(options);
  if (!agentsh) {
    return;
  }

  logger.debug(`Agentsh session ID: ${agentsh.sessionId}`);
  logger.debug(`Agentsh hardening version: ${agentsh.version ?? "unknown"}`);
  if (agentsh.versionLookupError) {
    logger.debug(
      `Agentsh version lookup failed: ${agentsh.versionLookupError}`,
    );
  }
}

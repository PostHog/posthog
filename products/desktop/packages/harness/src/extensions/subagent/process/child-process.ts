/**
 * Owns exactly one raw child process: spawning it, line-buffering its
 * stdout/stderr, and killing it. Agent-agnostic — knows nothing about pi
 * sessions, agents, or tasks. This is the only module in the extension that
 * imports `node:child_process`.
 */
import { type ChildProcess, spawn } from "node:child_process";

export interface SpawnChildProcessOptions {
  command: string;
  args: string[];
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  onStdoutLine?: (line: string) => void;
  onStderrChunk?: (chunk: string) => void;
}

export interface ChildProcessHandle {
  /** Resolves with the exit code once the process has exited, for any reason. */
  exited: Promise<number>;
  /** Idempotent: safe to call multiple times, and safe to call after exit. */
  kill: () => void;
}

const KILL_GRACE_PERIOD_MS = 5000;

export function spawnChildProcess(
  options: SpawnChildProcessOptions,
): ChildProcessHandle {
  const { command, args, cwd, env, onStdoutLine, onStderrChunk } = options;

  let proc: ChildProcess;
  try {
    proc = spawn(command, args, {
      cwd,
      env,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch {
    // `spawn()` can throw synchronously for some invalid inputs (e.g. a
    // malformed `cwd`/`env`) instead of emitting an async "error" event.
    // Callers (`run-agent.ts`, `process/pool.ts`, `chain.ts`) all rely on
    // `ChildProcessHandle` never throwing — only ever resolving `exited` —
    // so treat a synchronous spawn failure the same as the async "error"
    // case below: never started, exit code 1.
    return { exited: Promise.resolve(1), kill: () => {} };
  }

  let stdoutBuffer = "";
  proc.stdout?.on("data", (data: Buffer) => {
    stdoutBuffer += data.toString();
    const lines = stdoutBuffer.split("\n");
    stdoutBuffer = lines.pop() ?? "";
    for (const line of lines) onStdoutLine?.(line);
  });

  proc.stderr?.on("data", (data: Buffer) => {
    onStderrChunk?.(data.toString());
  });

  let killed = false;
  let killTimer: ReturnType<typeof setTimeout> | undefined;

  const kill = (): void => {
    if (killed) return;
    killed = true;
    proc.kill("SIGTERM");
    killTimer = setTimeout(() => {
      if (!proc.killed) proc.kill("SIGKILL");
    }, KILL_GRACE_PERIOD_MS);
  };

  const exited = new Promise<number>((resolve) => {
    proc.on("close", (code) => {
      if (killTimer) clearTimeout(killTimer);
      if (stdoutBuffer.trim()) onStdoutLine?.(stdoutBuffer);
      resolve(code ?? (killed ? 143 : 0));
    });
    proc.on("error", () => {
      if (killTimer) clearTimeout(killTimer);
      resolve(1);
    });
  });

  return { exited, kill };
}

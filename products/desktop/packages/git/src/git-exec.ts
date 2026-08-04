// Namespace import (not `{ execFile }`) so the renderer's browser bundle can
// resolve this node-only module against vite's `__vite-browser-external` stub,
// which has no named exports. execGit never runs in the browser.
import * as childProcess from "node:child_process";

export interface GitExecResult {
  stdout: string;
  stderr: string;
  exitCode: number;
  error?: string;
}

export interface GitExecOptions {
  cwd?: string;
  /** Merged over `process.env` rather than replacing it. */
  env?: Record<string, string>;
  /**
   * Kill the `git` subprocess after this many ms, so a clone or fetch that
   * stalls on the network can't hang the caller forever. Omit for no timeout.
   */
  timeoutMs?: number;
  maxBuffer?: number;
}

const DEFAULT_MAX_BUFFER = 32 * 1024 * 1024;

/**
 * Runs a `git` subcommand and resolves with its result, mirroring `execGh`.
 *
 * This is the raw-subprocess counterpart to the simple-git client: no repo
 * locking, no saga bookkeeping, and `GIT_CONFIG_*` in `env` is passed through
 * untouched. It suits callers that own the whole checkout for the duration of
 * the call, such as an agent cloning into its own scratch workspace.
 */
export function execGit(
  args: string[],
  options: GitExecOptions = {},
): Promise<GitExecResult> {
  const env = options.env ? { ...process.env, ...options.env } : process.env;

  return new Promise<GitExecResult>((resolve) => {
    childProcess.execFile(
      "git",
      args,
      {
        cwd: options.cwd,
        env,
        timeout: options.timeoutMs ?? 0,
        maxBuffer: options.maxBuffer ?? DEFAULT_MAX_BUFFER,
      },
      (error, stdout, stderr) => {
        if (!error) {
          resolve({ stdout, stderr, exitCode: 0 });
          return;
        }

        const err = error as Error & {
          code?: number | string;
          killed?: boolean;
          stdout?: string;
          stderr?: string;
        };
        // execFile kills the child on timeout (`killed` set, `code` null), so
        // report that as a timeout rather than an opaque signal death.
        const timedOut = err.killed === true && !!options.timeoutMs;
        const exitCode =
          typeof err.code === "number"
            ? err.code
            : err.code === "ENOENT"
              ? 127
              : 1;

        resolve({
          stdout: stdout ?? err.stdout ?? "",
          stderr: stderr ?? err.stderr ?? "",
          exitCode,
          error: timedOut
            ? `git timed out after ${options.timeoutMs}ms`
            : err.message,
        });
      },
    );
  });
}

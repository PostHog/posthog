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

// Failures worth retrying: server-side blips (5xx), interrupted transfers,
// our own timeout, and transport-level network errors. Deterministic failures
// (auth, missing refs, non-empty destination) are intentionally excluded —
// retrying them only wastes time.
const TRANSIENT_GIT_PATTERNS: readonly RegExp[] = [
  /The requested URL returned error: 5\d\d/,
  /\btimed out\b/i,
  /\bETIMEDOUT\b/,
  /\bECONNRESET\b/,
  /\bECONNREFUSED\b/,
  /\bEAI_AGAIN\b/,
  /connection reset/i,
  /Could not resolve host/i,
  /Failed to connect to/i,
  /early EOF/i,
  /RPC failed/i,
  /GnuTLS recv error/i,
];

export function isTransientGitFailure(res: GitExecResult): boolean {
  if (res.exitCode === 0) {
    return false;
  }
  const text = `${res.stderr} ${res.error ?? ""} ${res.stdout}`;
  return TRANSIENT_GIT_PATTERNS.some((re) => re.test(text));
}

export interface GitRetryOptions {
  maxAttempts?: number;
  /** Base backoff; attempt N waits `backoffMs * 2^(N-2)` before retrying. */
  backoffMs?: number;
}

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Runs `execGit`, retrying only on transient failures with exponential
 * backoff, mirroring `execGhWithRetry`. `exec` is injectable for tests;
 * production callers use the default.
 */
export async function execGitWithRetry(
  args: string[],
  options: GitExecOptions = {},
  retry: GitRetryOptions = {},
  exec: typeof execGit = execGit,
): Promise<GitExecResult> {
  const maxAttempts = retry.maxAttempts ?? 3;
  const backoffMs = retry.backoffMs ?? 500;

  let res = await exec(args, options);
  for (
    let attempt = 2;
    attempt <= maxAttempts && isTransientGitFailure(res);
    attempt++
  ) {
    await sleep(backoffMs * 2 ** (attempt - 2));
    res = await exec(args, options);
  }
  return res;
}

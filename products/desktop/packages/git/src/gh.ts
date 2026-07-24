// Namespace import (not `{ execFile }`) so the renderer's browser bundle can
// resolve this node-only module against vite's `__vite-browser-external` stub,
// which has no named exports. execGh never runs in the browser.
import * as childProcess from "node:child_process";

export interface GhExecResult {
  stdout: string;
  stderr: string;
  exitCode: number;
  error?: string;
}

export interface GhExecOptions {
  cwd?: string;
  env?: Record<string, string>;
  /**
   * Written to the child's stdin and then closed. Use with `gh api graphql
   * --input -` (or `gh api --input -`) to pass a JSON request body so complex
   * GraphQL variables are sent as real objects rather than `-F` string scalars.
   */
  input?: string;
  /**
   * Kill the `gh` subprocess after this many ms. Without it a stalled network
   * call (the symptom behind GitHub's `HTTP 499`) hangs the caller — and any
   * MCP tool awaiting it — indefinitely. Omit for no timeout.
   */
  timeoutMs?: number;
  /**
   * Max stdout/stderr bytes before the child is killed. Node's execFile
   * default is 1 MiB, which paginated `gh api` calls (PR files, comments)
   * blow past on busy PRs — the call then dies with "maxBuffer length
   * exceeded" instead of returning data.
   */
  maxBuffer?: number;
}

const DEFAULT_MAX_BUFFER = 32 * 1024 * 1024;

export function execGh(
  args: string[],
  options: GhExecOptions = {},
): Promise<GhExecResult> {
  const env = options.env ? { ...process.env, ...options.env } : process.env;

  return new Promise<GhExecResult>((resolve) => {
    const child = childProcess.execFile(
      "gh",
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
        // execFile kills the child on timeout (`killed` set, `code` null);
        // surface a recognizable message so retries treat it as transient.
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
            ? `gh timed out after ${options.timeoutMs}ms`
            : err.message,
        });
      },
    );

    if (options.input !== undefined) {
      child.stdin?.end(options.input);
    }
  });
}

// Failures worth retrying: server-side blips (5xx), the proxy "client closed"
// 499 we kept hitting from sandboxes, our own timeout, and transport-level
// network errors. Deterministic failures (auth, 404, 422, GraphQL validation)
// are intentionally excluded — retrying them only wastes time.
const TRANSIENT_GH_PATTERNS: readonly RegExp[] = [
  /HTTP 5\d\d/,
  /HTTP 499/,
  /\btimed out\b/i,
  /\bETIMEDOUT\b/,
  /\bECONNRESET\b/,
  /\bECONNREFUSED\b/,
  /\bEAI_AGAIN\b/,
  /connection reset/i,
];

export function isTransientGhFailure(res: GhExecResult): boolean {
  if (res.exitCode === 0) {
    return false;
  }
  const text = `${res.stderr} ${res.error ?? ""} ${res.stdout}`;
  return TRANSIENT_GH_PATTERNS.some((re) => re.test(text));
}

export interface GhRetryOptions {
  maxAttempts?: number;
  /** Base backoff; attempt N waits `backoffMs * 2^(N-2)` before retrying. */
  backoffMs?: number;
}

const sleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Runs `execGh`, retrying only on transient failures with exponential backoff.
 * `exec` is injectable for tests; production callers use the default.
 */
export async function execGhWithRetry(
  args: string[],
  options: GhExecOptions = {},
  retry: GhRetryOptions = {},
  exec: typeof execGh = execGh,
): Promise<GhExecResult> {
  const maxAttempts = retry.maxAttempts ?? 3;
  const backoffMs = retry.backoffMs ?? 500;

  let res = await exec(args, options);
  for (
    let attempt = 2;
    attempt <= maxAttempts && isTransientGhFailure(res);
    attempt++
  ) {
    await sleep(backoffMs * 2 ** (attempt - 2));
    res = await exec(args, options);
  }
  return res;
}

import { access, watch } from "node:fs";
import { basename, dirname } from "node:path";

export interface WaitForFileOptions {
  timeoutMs: number;
  fallbackPollMs?: number;
  onError?: (error: NodeJS.ErrnoException) => void;
}

export interface WaitForFileResult {
  waitedMs: number;
  timedOut: boolean;
}

export async function waitForFile(
  path: string,
  { timeoutMs, fallbackPollMs = 100, onError }: WaitForFileOptions,
): Promise<WaitForFileResult> {
  const startedAt = performance.now();
  let errorReported = false;
  const reportError = (error: NodeJS.ErrnoException): void => {
    if (errorReported) return;
    errorReported = true;
    onError?.(error);
  };
  if (await exists(path, reportError)) return { waitedMs: 0, timedOut: false };

  return await new Promise<WaitForFileResult>((resolve) => {
    let settled = false;
    let watcher: ReturnType<typeof watch> | undefined;

    const finish = (timedOut: boolean): void => {
      if (settled) return;
      settled = true;
      watcher?.close();
      clearInterval(poll);
      clearTimeout(timeout);
      const elapsedMs = Math.max(0, Math.round(performance.now() - startedAt));
      resolve({
        waitedMs: timedOut ? Math.max(timeoutMs, elapsedMs) : elapsedMs,
        timedOut,
      });
    };

    const check = (): void => {
      void exists(path, reportError).then((present) => {
        if (present) finish(false);
      });
    };

    const poll = setInterval(check, fallbackPollMs);
    const timeout = setTimeout(() => finish(true), timeoutMs);

    try {
      watcher = watch(dirname(path), (_event, filename) => {
        if (!filename || filename.toString() === basename(path)) check();
      });
      watcher.on("error", () => {
        watcher?.close();
        watcher = undefined;
      });
    } catch {
      watcher = undefined;
    }

    check();
  });
}

async function exists(
  path: string,
  onError?: (error: NodeJS.ErrnoException) => void,
): Promise<boolean> {
  return await new Promise<boolean>((resolve) => {
    access(path, (error) => {
      if (error && error.code !== "ENOENT") onError?.(error);
      resolve(!error);
    });
  });
}

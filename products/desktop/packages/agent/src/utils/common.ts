import type { Logger } from "./logger";

/**
 * Races an operation against a timeout.
 * Returns success with the value if the operation completes in time,
 * or timeout if the operation takes longer than the specified duration.
 */
export async function withTimeout<T>(
  operation: Promise<T>,
  timeoutMs: number,
): Promise<{ result: "success"; value: T } | { result: "timeout" }> {
  const timeoutPromise = new Promise<{ result: "timeout" }>((resolve) =>
    setTimeout(() => resolve({ result: "timeout" }), timeoutMs),
  );
  const operationPromise = operation.then((value) => ({
    result: "success" as const,
    value,
  }));
  return Promise.race([operationPromise, timeoutPromise]);
}

/**
 * Races an operation against an AbortSignal.
 * Returns success with the value if the operation settles before the signal
 * aborts, or aborted otherwise. The operation itself is not cancelled: a
 * settle after abort is ignored, and a rejection is always observed so it
 * never surfaces as an unhandled rejection.
 *
 * Use this instead of `Promise.race([operation, abortPromise])` when racing
 * in a loop: each race call parks a reaction on the long-lived abort promise
 * that retains that iteration's settled value until the abort promise itself
 * settles. The abort listener here is removed as soon as the operation
 * settles, so per-call state is reclaimed immediately.
 */
export function withAbort<T>(
  operation: Promise<T>,
  signal: AbortSignal,
): Promise<{ result: "success"; value: T } | { result: "aborted" }> {
  return new Promise((resolve, reject) => {
    const onAbort = () => resolve({ result: "aborted" });
    if (signal.aborted) {
      onAbort();
    } else {
      signal.addEventListener("abort", onAbort, { once: true });
    }
    operation.then(
      (value) => {
        signal.removeEventListener("abort", onAbort);
        resolve({ result: "success", value });
      },
      (error) => {
        signal.removeEventListener("abort", onAbort);
        reject(error);
      },
    );
  });
}

export const IS_ROOT =
  typeof process !== "undefined" &&
  (process.geteuid?.() ?? process.getuid?.()) === 0;

export const ALLOW_BYPASS = !IS_ROOT || !!process.env.IS_SANDBOX;

/**
 * A cloud sandbox run, as opposed to a local desktop session. `taskRunId` is
 * used by both desktop and cloud for persistence, so it must not imply cloud.
 */
export function isCloudRun(
  meta: { environment?: "local" | "cloud" } | undefined,
): boolean {
  if (meta?.environment) {
    return meta.environment === "cloud";
  }
  return !!process.env.IS_SANDBOX;
}

export function unreachable(value: never, logger: Logger): void {
  let valueAsString: string;
  try {
    valueAsString = JSON.stringify(value);
  } catch {
    valueAsString = String(value);
  }
  logger.error(`Unexpected case: ${valueAsString}`);
}

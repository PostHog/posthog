/**
 * Bounded concurrent execution over an arbitrary set of abortable async
 * tasks. Knows nothing about agents, tasks, or processes — `run-agent.ts`'s
 * `runAgent` already kills its own child process when the signal it's given
 * aborts, so `runPool` only has to fan a single abort out to every in-flight
 * task's own signal; it doesn't need to track child-process handles itself.
 * That's what makes "abort kills every outstanding child" hold: each task is
 * individually responsible for its own cleanup on abort, and every task here
 * is always given a signal that aborts together.
 */

export interface RunPoolOptions {
  concurrency: number;
  signal?: AbortSignal;
}

export async function runPool<TIn, TOut>(
  items: TIn[],
  options: RunPoolOptions,
  fn: (item: TIn, index: number, signal: AbortSignal) => Promise<TOut>,
): Promise<TOut[]> {
  if (items.length === 0) return [];

  const controller = new AbortController();
  const forwardAbort = () => controller.abort(options.signal?.reason);
  if (options.signal) {
    if (options.signal.aborted) forwardAbort();
    else options.signal.addEventListener("abort", forwardAbort, { once: true });
  }

  const limit = Math.max(1, Math.min(options.concurrency, items.length));
  const results: TOut[] = new Array(items.length);
  let nextIndex = 0;
  // If any task's `fn` throws, we abort every other still-running task before
  // surfacing the error, so a single failure can't leave orphaned work (and
  // orphaned child processes, for `run-agent.ts`'s use of this) running
  // unobserved in the background. Workers never reject themselves — errors
  // are captured here and re-thrown once, after every worker has actually
  // finished — so `Promise.all` always resolves and we don't risk additional
  // unhandled rejections from other workers failing after the first one.
  let firstError: unknown;
  let hasError = false;

  const worker = async (): Promise<void> => {
    for (;;) {
      if (hasError) return;
      const current = nextIndex++;
      if (current >= items.length) return;
      try {
        results[current] = await fn(items[current], current, controller.signal);
      } catch (error) {
        if (!hasError) {
          hasError = true;
          firstError = error;
          controller.abort();
        }
        return;
      }
    }
  };

  try {
    await Promise.all(new Array(limit).fill(null).map(() => worker()));
  } finally {
    options.signal?.removeEventListener("abort", forwardAbort);
  }

  if (hasError) throw firstError;
  return results;
}

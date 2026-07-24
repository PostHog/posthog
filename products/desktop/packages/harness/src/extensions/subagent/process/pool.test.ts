import { describe, expect, it } from "vitest";
import { runPool } from "./pool";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("runPool", () => {
  it("returns an empty array for no items without touching fn", async () => {
    const results = await runPool<number, number>(
      [],
      { concurrency: 4 },
      () => {
        throw new Error("should not be called");
      },
    );
    expect(results).toEqual([]);
  });

  it("preserves result order regardless of completion order", async () => {
    const delays = [30, 10, 20];
    const results = await runPool(
      delays,
      { concurrency: 3 },
      async (delay, index) => {
        await new Promise((r) => setTimeout(r, delay));
        return index;
      },
    );
    expect(results).toEqual([0, 1, 2]);
  });

  it("never runs more than `concurrency` tasks at once", async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    const items = Array.from({ length: 8 }, (_, i) => i);

    await runPool(items, { concurrency: 3 }, async () => {
      inFlight++;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise((r) => setTimeout(r, 5));
      inFlight--;
    });

    expect(maxInFlight).toBeLessThanOrEqual(3);
  });

  it("aborts every outstanding task's own signal when the caller's signal aborts", async () => {
    const controller = new AbortController();
    const abortedFlags: boolean[] = [false, false, false];
    const started = [deferred<void>(), deferred<void>(), deferred<void>()];

    const run = runPool(
      [0, 1, 2],
      { concurrency: 3, signal: controller.signal },
      async (item, index, taskSignal) => {
        started[index].resolve();
        await new Promise<void>((resolve) => {
          if (taskSignal.aborted) {
            abortedFlags[index] = true;
            resolve();
            return;
          }
          taskSignal.addEventListener(
            "abort",
            () => {
              abortedFlags[index] = true;
              resolve();
            },
            { once: true },
          );
        });
        return item;
      },
    );

    await Promise.all(started.map((d) => d.promise));
    controller.abort();
    await run;

    expect(abortedFlags).toEqual([true, true, true]);
  });

  it("aborts every other in-flight task's signal when one task's fn throws, and rejects with that error", async () => {
    const abortedFlags: boolean[] = [false, false, false];
    const started = [deferred<void>(), deferred<void>(), deferred<void>()];

    const run = runPool(
      [0, 1, 2],
      { concurrency: 3 },
      async (item, index, taskSignal) => {
        started[index].resolve();
        if (index === 0) {
          await new Promise((r) => setTimeout(r, 10));
          throw new Error("boom");
        }
        await new Promise<void>((resolve) => {
          if (taskSignal.aborted) {
            abortedFlags[index] = true;
            resolve();
            return;
          }
          taskSignal.addEventListener(
            "abort",
            () => {
              abortedFlags[index] = true;
              resolve();
            },
            { once: true },
          );
        });
        return item;
      },
    );

    await Promise.all(started.map((d) => d.promise));
    await expect(run).rejects.toThrow("boom");
    expect(abortedFlags).toEqual([false, true, true]);
  });

  it("surfaces only the first error when multiple tasks fail, without unhandled rejections", async () => {
    const unhandledRejections: unknown[] = [];
    const onUnhandledRejection = (reason: unknown) =>
      unhandledRejections.push(reason);
    process.on("unhandledRejection", onUnhandledRejection);

    try {
      const run = runPool(
        [0, 1, 2],
        { concurrency: 3 },
        async (_item, index) => {
          await new Promise((r) => setTimeout(r, index * 5));
          throw new Error(`fail-${index}`);
        },
      );
      await expect(run).rejects.toThrow("fail-0");
      await new Promise((r) => setTimeout(r, 20));
      expect(unhandledRejections).toEqual([]);
    } finally {
      process.removeListener("unhandledRejection", onUnhandledRejection);
    }
  });

  it("does not run further queued items once a task has failed", async () => {
    const started: number[] = [];
    await runPool([0, 1, 2, 3, 4], { concurrency: 1 }, async (item, index) => {
      started.push(index);
      if (index === 1) throw new Error("boom");
      return item;
    }).catch(() => {});

    expect(started).toEqual([0, 1]);
  });
});

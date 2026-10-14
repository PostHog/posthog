import { describe, expect, it } from "vitest";
import { AsyncMutex } from "./async-mutex";

describe("AsyncMutex", () => {
  it("acquires lock when unlocked", async () => {
    const mutex = new AsyncMutex();

    expect(mutex.isLocked()).toBe(false);
    await mutex.acquire();
    expect(mutex.isLocked()).toBe(true);
  });

  it("releases lock", async () => {
    const mutex = new AsyncMutex();

    await mutex.acquire();
    expect(mutex.isLocked()).toBe(true);

    mutex.release();
    expect(mutex.isLocked()).toBe(false);
  });

  it("queues concurrent acquires", async () => {
    const mutex = new AsyncMutex();
    const order: number[] = [];

    await mutex.acquire();
    expect(mutex.queueLength).toBe(0);

    const promise1 = mutex.acquire().then(() => order.push(1));
    const promise2 = mutex.acquire().then(() => order.push(2));

    expect(mutex.queueLength).toBe(2);

    mutex.release();
    await promise1;
    expect(order).toEqual([1]);

    mutex.release();
    await promise2;
    expect(order).toEqual([1, 2]);
  });

  it("processes queue in FIFO order", async () => {
    const mutex = new AsyncMutex();
    const order: number[] = [];

    await mutex.acquire();

    const promises = [1, 2, 3, 4, 5].map((n) =>
      mutex.acquire().then(() => {
        order.push(n);
      }),
    );

    expect(mutex.queueLength).toBe(5);

    for (let i = 0; i < 5; i++) {
      mutex.release();
      await promises[i];
    }

    expect(order).toEqual([1, 2, 3, 4, 5]);
  });

  it("serializes concurrent operations", async () => {
    const mutex = new AsyncMutex();
    const results: string[] = [];

    const operation = async (id: string, delay: number) => {
      await mutex.acquire();
      try {
        results.push(`${id}-start`);
        await new Promise((r) => setTimeout(r, delay));
        results.push(`${id}-end`);
      } finally {
        mutex.release();
      }
    };

    await Promise.all([
      operation("a", 10),
      operation("b", 5),
      operation("c", 1),
    ]);

    expect(results).toEqual([
      "a-start",
      "a-end",
      "b-start",
      "b-end",
      "c-start",
      "c-end",
    ]);
  });

  it("handles release without acquire gracefully", () => {
    const mutex = new AsyncMutex();

    expect(mutex.isLocked()).toBe(false);
    mutex.release();
    expect(mutex.isLocked()).toBe(false);
  });
});

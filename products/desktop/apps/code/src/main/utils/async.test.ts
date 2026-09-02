import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const warn = vi.hoisted(() => vi.fn());

vi.mock("./logger", () => ({
  logger: {
    scope: () => ({
      info: vi.fn(),
      error: vi.fn(),
      warn,
      debug: vi.fn(),
    }),
  },
}));

import { subscribeWithTimeout, withTimeout } from "./async";

interface FakeSubscription {
  unsubscribe: () => Promise<unknown>;
}

const makeSubscription = (
  unsubscribeImpl: () => Promise<unknown> = () => Promise.resolve(),
): FakeSubscription & { unsubscribe: ReturnType<typeof vi.fn> } => {
  const unsubscribe = vi.fn(
    unsubscribeImpl,
  ) as unknown as (() => Promise<unknown>) & ReturnType<typeof vi.fn>;
  return { unsubscribe };
};

const deferred = <T>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

describe("withTimeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    warn.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns success with the value when the operation resolves first", async () => {
    const result = await withTimeout(Promise.resolve("done"), 1000);
    expect(result).toEqual({ result: "success", value: "done" });
  });

  it("returns timeout when the operation is slower than the deadline", async () => {
    const { promise } = deferred<string>();
    const racePromise = withTimeout(promise, 1000);
    await vi.advanceTimersByTimeAsync(1000);
    expect(await racePromise).toEqual({ result: "timeout" });
  });

  it("clears the timeout timer on success", async () => {
    const clearSpy = vi.spyOn(globalThis, "clearTimeout");
    await withTimeout(Promise.resolve("done"), 1000);
    expect(clearSpy).toHaveBeenCalledTimes(1);
  });
});

describe("subscribeWithTimeout", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    warn.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns success and the subscription when subscribe resolves first", async () => {
    const sub = makeSubscription();
    const result = await subscribeWithTimeout(
      Promise.resolve(sub),
      1000,
      "test",
    );
    expect(result).toEqual({ result: "success", subscription: sub });
    expect(sub.unsubscribe).not.toHaveBeenCalled();
  });

  it("clears the timeout timer on success", async () => {
    const clearSpy = vi.spyOn(globalThis, "clearTimeout");
    await subscribeWithTimeout(
      Promise.resolve(makeSubscription()),
      1000,
      "test",
    );
    expect(clearSpy).toHaveBeenCalledTimes(1);
  });

  it("returns timeout and unsubscribes the late subscription", async () => {
    const sub = makeSubscription();
    const { promise, resolve } = deferred<FakeSubscription>();

    const racePromise = subscribeWithTimeout(promise, 1000, "late-sub");
    await vi.advanceTimersByTimeAsync(1000);
    expect(await racePromise).toEqual({ result: "timeout" });

    resolve(sub);
    await vi.runAllTimersAsync();
    await Promise.resolve();

    expect(sub.unsubscribe).toHaveBeenCalledTimes(1);
  });

  it("logs a warning when the late unsubscribe rejects", async () => {
    const sub = makeSubscription(() => Promise.reject(new Error("nope")));
    const { promise, resolve } = deferred<FakeSubscription>();

    const racePromise = subscribeWithTimeout(promise, 1000, "boom");
    await vi.advanceTimersByTimeAsync(1000);
    await racePromise;

    resolve(sub);
    await vi.runAllTimersAsync();
    await Promise.resolve();
    await Promise.resolve();

    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("Failed to tear down late subscription (boom)"),
      expect.any(Error),
    );
  });

  it("logs a warning when the subscribe promise rejects after the timeout", async () => {
    const { promise, reject } = deferred<FakeSubscription>();

    const racePromise = subscribeWithTimeout(promise, 1000, "rejected-late");
    await vi.advanceTimersByTimeAsync(1000);
    await racePromise;

    reject(new Error("subscribe blew up"));
    await vi.runAllTimersAsync();
    await Promise.resolve();
    await Promise.resolve();

    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining(
        "Late subscribe rejected after timeout (rejected-late)",
      ),
      expect.any(Error),
    );
  });

  it("propagates a subscribe rejection that beats the timeout", async () => {
    const failing = Promise.reject(new Error("immediate fail"));
    await expect(
      subscribeWithTimeout(failing, 1000, "early-fail"),
    ).rejects.toThrow("immediate fail");
  });
});

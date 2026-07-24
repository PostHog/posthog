import { describe, expect, it, vi } from "vitest";
import { TypedEventEmitter } from "./typed-event-emitter";

interface Events {
  data: { value: number };
  done: undefined;
}

function collect<T>(iterable: AsyncIterable<T>, count: number): Promise<T[]> {
  return (async () => {
    const out: T[] = [];
    for await (const item of iterable) {
      out.push(item);
      if (out.length >= count) break;
    }
    return out;
  })();
}

describe("TypedEventEmitter", () => {
  it("calls on() listeners in registration order with the payload", () => {
    const e = new TypedEventEmitter<Events>();
    const calls: number[] = [];
    e.on("data", (p) => calls.push(p.value * 1));
    e.on("data", (p) => calls.push(p.value * 10));
    const had = e.emit("data", { value: 2 });
    expect(had).toBe(true);
    expect(calls).toEqual([2, 20]);
  });

  it("emit returns false when there are no listeners", () => {
    const e = new TypedEventEmitter<Events>();
    expect(e.emit("data", { value: 1 })).toBe(false);
  });

  it("once() fires exactly once", () => {
    const e = new TypedEventEmitter<Events>();
    const fn = vi.fn();
    e.once("data", fn);
    e.emit("data", { value: 1 });
    e.emit("data", { value: 2 });
    expect(fn).toHaveBeenCalledTimes(1);
    expect(fn).toHaveBeenCalledWith({ value: 1 });
    expect(e.listenerCount("data")).toBe(0);
  });

  it("off() removes a listener; removeListener matches once-wrappers by original", () => {
    const e = new TypedEventEmitter<Events>();
    const fn = vi.fn();
    e.on("data", fn);
    e.off("data", fn);
    e.emit("data", { value: 1 });
    expect(fn).not.toHaveBeenCalled();

    const onceFn = vi.fn();
    e.once("data", onceFn);
    e.removeListener("data", onceFn);
    e.emit("data", { value: 1 });
    expect(onceFn).not.toHaveBeenCalled();
    expect(e.listenerCount("data")).toBe(0);
  });

  it("prependListener / prependOnceListener run before existing listeners", () => {
    const e = new TypedEventEmitter<Events>();
    const order: string[] = [];
    e.on("data", () => order.push("a"));
    e.prependListener("data", () => order.push("pre"));
    e.emit("data", { value: 1 });
    expect(order).toEqual(["pre", "a"]);
  });

  it("removeAllListeners clears one event or all events", () => {
    const e = new TypedEventEmitter<Events>();
    e.on("data", () => {});
    e.on("done", () => {});
    e.removeAllListeners("data");
    expect(e.listenerCount("data")).toBe(0);
    expect(e.listenerCount("done")).toBe(1);
    e.removeAllListeners();
    expect(e.eventNames()).toEqual([]);
  });

  it("listeners() returns originals, rawListeners() returns once-wrappers", () => {
    const e = new TypedEventEmitter<Events>();
    const fn = () => {};
    e.once("data", fn);
    expect(e.listeners("data")).toEqual([fn]);
    expect(e.rawListeners("data")[0]).not.toBe(fn);
  });

  it("eventNames lists events with listeners; get/setMaxListeners round-trip", () => {
    const e = new TypedEventEmitter<Events>();
    e.on("data", () => {});
    expect(e.eventNames()).toEqual(["data"]);
    e.setMaxListeners(99);
    expect(e.getMaxListeners()).toBe(99);
  });

  it("a listener removed mid-emit still does not fire again within the same emit", () => {
    const e = new TypedEventEmitter<Events>();
    const seen: string[] = [];
    const b = () => seen.push("b");
    e.on("data", () => {
      seen.push("a");
      e.off("data", b);
    });
    e.on("data", b);
    e.emit("data", { value: 1 });
    // snapshot semantics: b was already scheduled in this emit
    expect(seen).toEqual(["a", "b"]);
    e.emit("data", { value: 2 });
    expect(seen).toEqual(["a", "b", "a"]);
  });

  it("emit does not surface a rejecting async listener as an unhandled rejection", async () => {
    const e = new TypedEventEmitter<Events>();
    const unhandled = vi.fn();
    process.on("unhandledRejection", unhandled);
    try {
      // An async listener whose body rejects (here: throws synchronously before
      // its first await, the shape of the DB-not-initialized bug this guards).
      e.on("data", async () => {
        throw new Error("listener boom");
      });
      const other = vi.fn();
      e.on("data", other);

      expect(e.emit("data", { value: 1 })).toBe(true);
      // Later listeners still run despite the earlier one rejecting.
      expect(other).toHaveBeenCalledWith({ value: 1 });

      // Give the microtask queue and the unhandledRejection task a chance.
      await new Promise((resolve) => setTimeout(resolve, 0));
      expect(unhandled).not.toHaveBeenCalled();
    } finally {
      process.off("unhandledRejection", unhandled);
    }
  });

  it("toIterable yields events that arrive while awaiting", async () => {
    const e = new TypedEventEmitter<Events>();
    const result = collect(e.toIterable("data"), 2);
    await Promise.resolve();
    e.emit("data", { value: 1 });
    e.emit("data", { value: 2 });
    expect(await result).toEqual([{ value: 1 }, { value: 2 }]);
  });

  it("toIterable buffers events that arrive between iterations (no drops)", async () => {
    const e = new TypedEventEmitter<Events>();
    // Emit a burst before the consumer pulls the second item.
    const received: number[] = [];
    const iterable = e.toIterable("data");
    const iterator = iterable[Symbol.asyncIterator]();

    const first = iterator.next();
    await Promise.resolve();
    e.emit("data", { value: 1 });
    e.emit("data", { value: 2 });
    e.emit("data", { value: 3 });
    received.push((await first).value?.value);
    received.push((await iterator.next()).value?.value);
    received.push((await iterator.next()).value?.value);
    expect(received).toEqual([1, 2, 3]);
  });

  it("toIterable stops cleanly when the abort signal fires and removes its listener", async () => {
    const e = new TypedEventEmitter<Events>();
    const controller = new AbortController();
    const done = (async () => {
      const out: number[] = [];
      for await (const item of e.toIterable("data", {
        signal: controller.signal,
      })) {
        out.push(item.value);
      }
      return out;
    })();
    await Promise.resolve();
    e.emit("data", { value: 1 });
    await Promise.resolve();
    controller.abort();
    expect(await done).toEqual([1]);
    expect(e.listenerCount("data")).toBe(0);
  });

  it("toIterable returns immediately if the signal is already aborted", async () => {
    const e = new TypedEventEmitter<Events>();
    const controller = new AbortController();
    controller.abort();
    const out: number[] = [];
    for await (const item of e.toIterable("data", {
      signal: controller.signal,
    })) {
      out.push(item.value);
    }
    expect(out).toEqual([]);
    expect(e.listenerCount("data")).toBe(0);
  });
});

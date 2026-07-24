import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSuggestionLoader } from "./suggestionLoader";

interface Item {
  id: string;
  label: string;
}

const flush = () => new Promise<void>((r) => setTimeout(r, 0));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("createSuggestionLoader", () => {
  describe("sync items", () => {
    it("returns items immediately and reports not loading", () => {
      const loader = createSuggestionLoader<Item>({
        items: (q) => [{ id: q, label: q }],
      });

      expect(loader.load("hello")).toEqual([{ id: "hello", label: "hello" }]);
      expect(loader.getState()).toEqual({
        items: [{ id: "hello", label: "hello" }],
        loading: false,
      });
    });
  });

  describe("async items", () => {
    it("returns cached items synchronously and publishes results later", async () => {
      const loader = createSuggestionLoader<Item>({
        items: async (q) => [{ id: q, label: q }],
      });
      const updates: Array<{ items: Item[]; loading: boolean }> = [];
      loader.subscribe((state) => updates.push(state));

      const firstReturn = loader.load("a");

      expect(firstReturn).toEqual([]);
      expect(updates.at(-1)).toEqual({ items: [], loading: true });

      await flush();

      expect(loader.getState()).toEqual({
        items: [{ id: "a", label: "a" }],
        loading: false,
      });
      expect(updates.at(-1)).toEqual({
        items: [{ id: "a", label: "a" }],
        loading: false,
      });
    });

    it("returns the previously cached items while a new fetch is in flight", async () => {
      const first = deferred<Item[]>();
      const second = deferred<Item[]>();
      let callIndex = 0;
      const loader = createSuggestionLoader<Item>({
        items: () => (callIndex++ === 0 ? first.promise : second.promise),
      });

      loader.load("first");
      first.resolve([{ id: "1", label: "first" }]);
      await flush();

      const secondReturn = loader.load("second");
      expect(secondReturn).toEqual([{ id: "1", label: "first" }]);
      expect(loader.getState().loading).toBe(true);

      second.resolve([]);
      await flush();
    });

    it("drops stale async results when a newer query has started", async () => {
      const first = deferred<Item[]>();
      const second = deferred<Item[]>();
      let callIndex = 0;
      const loader = createSuggestionLoader<Item>({
        items: () => (callIndex++ === 0 ? first.promise : second.promise),
      });

      loader.load("a");
      loader.load("b");

      first.resolve([{ id: "stale", label: "stale" }]);
      await flush();

      expect(loader.getState()).toEqual({ items: [], loading: true });

      second.resolve([{ id: "fresh", label: "fresh" }]);
      await flush();

      expect(loader.getState()).toEqual({
        items: [{ id: "fresh", label: "fresh" }],
        loading: false,
      });
    });
  });

  describe("debounce", () => {
    beforeEach(() => {
      vi.useFakeTimers();
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("delays invoking loadItems until after the debounce window", async () => {
      const loadItems = vi
        .fn<(q: string) => Promise<Item[]>>()
        .mockResolvedValue([{ id: "ok", label: "ok" }]);
      const loader = createSuggestionLoader<Item>({
        items: loadItems,
        debounceMs: 200,
      });

      loader.load("a");
      loader.load("ab");
      loader.load("abc");

      expect(loadItems).not.toHaveBeenCalled();
      expect(loader.getState().loading).toBe(true);

      await vi.advanceTimersByTimeAsync(200);

      expect(loadItems).toHaveBeenCalledTimes(1);
      expect(loadItems).toHaveBeenCalledWith("abc");
    });
  });

  describe("reset", () => {
    it("clears cached items and publishes the empty state", async () => {
      const loader = createSuggestionLoader<Item>({
        items: async (q) => [{ id: q, label: q }],
      });

      loader.load("x");
      await flush();
      expect(loader.getState().items).toHaveLength(1);

      loader.reset();
      expect(loader.getState()).toEqual({ items: [], loading: false });
    });

    it("prevents an in-flight fetch from updating state after reset", async () => {
      const pending = deferred<Item[]>();
      const loader = createSuggestionLoader<Item>({
        items: () => pending.promise,
      });

      loader.load("a");
      loader.reset();

      pending.resolve([{ id: "late", label: "late" }]);
      await flush();

      expect(loader.getState()).toEqual({ items: [], loading: false });
    });
  });
});

import { expect, it, vi } from "vitest";

// Storage is IPC-backed and async in the app, so reads land after first paint.
// Everything here turns on that gap.
const readDelayMs = 5;
async function freshStore(stored: Record<string, string> | null) {
  vi.resetModules();
  vi.doMock("@posthog/ui/shell/rendererStorage", () => ({
    electronStorage: {
      getItem: async () => {
        await new Promise((r) => setTimeout(r, readDelayMs));
        return stored
          ? { state: { lastSeenByChannel: stored }, version: 0 }
          : null;
      },
      setItem: async () => {},
      removeItem: async () => {},
    },
  }));
  const { useChannelSeenStore } = await import("./channelSeenStore");
  return useChannelSeenStore;
}

const settle = () => new Promise((r) => setTimeout(r, readDelayMs * 4));

it("is not hydrated until the persisted map arrives", async () => {
  const store = await freshStore({ c1: "2026-01-01T00:00:00.000Z" });
  expect(store.getState().hasHydrated).toBe(false);
  expect(store.getState().lastSeenByChannel).toEqual({});

  await settle();
  expect(store.getState().hasHydrated).toBe(true);
  expect(store.getState().lastSeenByChannel.c1).toBe(
    "2026-01-01T00:00:00.000Z",
  );
});

it("keeps a stamp written before hydration instead of losing it to the stored map", async () => {
  const store = await freshStore({ c1: "2026-01-01T00:00:00.000Z" });

  // A channel opened during boot marks itself read before storage answers.
  store.getState().markChannelSeen("c2", "2026-07-16T10:00:00.000Z");
  await settle();

  expect(store.getState().lastSeenByChannel).toEqual({
    c1: "2026-01-01T00:00:00.000Z",
    c2: "2026-07-16T10:00:00.000Z",
  });
});

it("keeps the later visit when a channel is stamped on both sides of hydration", async () => {
  const store = await freshStore({ c1: "2026-01-01T00:00:00.000Z" });
  store.getState().markChannelSeen("c1", "2026-07-16T10:00:00.000Z");
  await settle();
  expect(store.getState().lastSeenByChannel.c1).toBe(
    "2026-07-16T10:00:00.000Z",
  );
});

it("hydrates even with nothing stored, so a first run isn't stuck unhydrated", async () => {
  const store = await freshStore(null);
  await settle();
  expect(store.getState().hasHydrated).toBe(true);
  expect(store.getState().lastSeenByChannel).toEqual({});
});

it("never walks a stamp backwards", async () => {
  const store = await freshStore(null);
  await settle();
  store.getState().markChannelSeen("c1", "2026-07-16T10:00:00.000Z");
  store.getState().markChannelSeen("c1", "2026-07-16T09:00:00.000Z");
  expect(store.getState().lastSeenByChannel.c1).toBe(
    "2026-07-16T10:00:00.000Z",
  );
});

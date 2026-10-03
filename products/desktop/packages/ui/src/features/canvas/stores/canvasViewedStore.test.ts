import { expect, it, vi } from "vitest";

const readDelayMs = 5;

async function freshStore(
  stored: Record<string, number>,
): Promise<typeof import("./canvasViewedStore").useCanvasViewedStore> {
  vi.resetModules();
  vi.doMock("@posthog/ui/shell/rendererStorage", () => ({
    electronStorage: {
      getItem: async () => {
        await new Promise((resolve) => setTimeout(resolve, readDelayMs));
        return {
          state: { lastViewedAtByCanvasId: stored },
          version: 0,
        };
      },
      setItem: async () => {},
      removeItem: async () => {},
    },
  }));
  const { useCanvasViewedStore } = await import("./canvasViewedStore");
  return useCanvasViewedStore;
}

it("keeps the latest view when storage hydrates", async () => {
  const store = await freshStore({ first: 10, stored: 30 });
  store.getState().markCanvasViewed("first", 20);
  store.getState().markCanvasViewed("current", 40);

  await vi.waitFor(() => {
    expect(store.getState().lastViewedAtByCanvasId).toEqual({
      first: 20,
      stored: 30,
      current: 40,
    });
  });

  store.getState().markCanvasViewed("current", 35);
  expect(store.getState().lastViewedAtByCanvasId.current).toBe(40);
});

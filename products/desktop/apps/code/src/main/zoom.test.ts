import { EventEmitter } from "node:events";
import { beforeEach, describe, expect, it, vi } from "vitest";

const store = vi.hoisted(() => {
  const state = { zoomLevel: 0.5 };
  return {
    get: vi.fn(() => state.zoomLevel),
    save: vi.fn((level: number) => {
      state.zoomLevel = level;
    }),
    state,
  };
});

vi.mock("./utils/store", () => ({
  windowStateStore: { get: store.get },
  saveZoomLevel: store.save,
}));

import { adjustWindowZoom, restoreWindowZoom, setupWindowZoom } from "./zoom";

class FakeWebContents extends EventEmitter {
  public destroyed = false;
  public readonly setZoomLevelCalls: number[] = [];
  public zoomLevel = 0;

  public isDestroyed(): boolean {
    return this.destroyed;
  }

  public getZoomLevel(): number {
    return this.zoomLevel;
  }

  public setZoomLevel(level: number): void {
    this.setZoomLevelCalls.push(level);
    this.zoomLevel = level;
  }
}

class FakeWindow extends EventEmitter {
  public readonly webContents = new FakeWebContents();
}

type ZoomWindow = Parameters<typeof adjustWindowZoom>[0];

function createWindow(): FakeWindow & ZoomWindow {
  return new FakeWindow() as FakeWindow & ZoomWindow;
}

describe("window zoom", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    store.state.zoomLevel = 0.5;
    store.get.mockReset();
    store.get.mockImplementation(() => store.state.zoomLevel);
    store.save.mockReset();
    store.save.mockImplementation((level: number) => {
      store.state.zoomLevel = level;
    });
  });

  it("adjusts from the persisted level when Chromium has reset", () => {
    const window = createWindow();
    window.webContents.zoomLevel = 0;

    adjustWindowZoom(window, 0.5);

    expect({
      zoomLevel: window.webContents.zoomLevel,
      saved: store.save.mock.calls,
    }).toEqual({
      zoomLevel: 1,
      saved: [[1]],
    });
  });

  it("restores the persisted level after maximizing", () => {
    const window = createWindow();
    setupWindowZoom(window);
    window.webContents.zoomLevel = 0;

    window.emit("maximize");
    vi.runAllTimers();

    expect(window.webContents.zoomLevel).toBe(0.5);
  });

  it("restores the persisted level after renderer reloads", () => {
    const window = createWindow();
    setupWindowZoom(window);
    window.webContents.zoomLevel = 0;

    window.webContents.emit("did-finish-load");

    expect(window.webContents.zoomLevel).toBe(0.5);
  });

  it("restores the current level after an external window resize", () => {
    const window = createWindow();
    setupWindowZoom(window);

    window.webContents.emit("zoom-changed", { preventDefault: vi.fn() }, "in");
    vi.runAllTimers();
    window.webContents.zoomLevel = 0;

    window.emit("resize");
    vi.runAllTimers();
    const restoredZoomLevel = window.webContents.zoomLevel;
    adjustWindowZoom(window, 0.5);

    expect({
      restoredZoomLevel,
      zoomLevel: window.webContents.zoomLevel,
      saved: store.save.mock.calls,
    }).toEqual({
      restoredZoomLevel: 1,
      zoomLevel: 1.5,
      saved: [[1], [1.5]],
    });
  });

  it.each([
    ["in", 1],
    ["out", 0],
  ] as const)(
    "applies wheel zoom %s from the persisted level",
    (direction, expected) => {
      const window = createWindow();
      setupWindowZoom(window);
      const event = { preventDefault: vi.fn() };

      window.webContents.emit("zoom-changed", event, direction);
      vi.runAllTimers();

      expect({
        prevented: event.preventDefault.mock.calls.length,
        zoomLevel: window.webContents.zoomLevel,
        saved: store.save.mock.calls,
      }).toEqual({
        prevented: 1,
        zoomLevel: expected,
        saved: [[expected]],
      });
    },
  );

  it.each(["resize", "resized"] as const)(
    "keeps wheel zoom after %s",
    (resizeEvent) => {
      const window = createWindow();
      setupWindowZoom(window);

      window.webContents.emit(
        "zoom-changed",
        { preventDefault: vi.fn() },
        "in",
      );
      window.emit(resizeEvent);
      vi.runAllTimers();

      expect({
        zoomLevel: window.webContents.zoomLevel,
        saved: store.save.mock.calls,
      }).toEqual({
        zoomLevel: 1,
        saved: [[1]],
      });
    },
  );

  it("skips redundant restoration during a resize storm", () => {
    const window = createWindow();
    setupWindowZoom(window);
    window.webContents.zoomLevel = 0.5;

    window.emit("resize");
    vi.runAllTimers();
    vi.advanceTimersByTime(16);
    window.emit("resize");
    vi.runAllTimers();
    const callsBeforeReset = [...window.webContents.setZoomLevelCalls];

    window.webContents.zoomLevel = 0;
    window.emit("resize");
    vi.runAllTimers();

    expect({
      callsBeforeReset,
      callsAfterReset: window.webContents.setZoomLevelCalls,
    }).toEqual({
      callsBeforeReset: [],
      callsAfterReset: [0.5],
    });
  });

  it("ignores queued zoom work after the window is destroyed", () => {
    const window = createWindow();
    setupWindowZoom(window);

    window.webContents.emit("zoom-changed", { preventDefault: vi.fn() }, "in");
    window.emit("resize");
    window.webContents.destroyed = true;
    vi.runAllTimers();

    expect({
      zoomLevelCalls: window.webContents.setZoomLevelCalls,
      saved: store.save.mock.calls,
    }).toEqual({
      zoomLevelCalls: [],
      saved: [],
    });
  });

  it("keeps wheel zoom after a renderer reload", () => {
    const window = createWindow();
    setupWindowZoom(window);

    window.webContents.emit("zoom-changed", { preventDefault: vi.fn() }, "in");
    window.webContents.emit("did-finish-load");
    vi.runAllTimers();

    expect({
      zoomLevel: window.webContents.zoomLevel,
      saved: store.save.mock.calls,
    }).toEqual({
      zoomLevel: 1,
      saved: [[1]],
    });
  });

  it("serializes wheel and menu zoom changes", () => {
    const window = createWindow();
    setupWindowZoom(window);

    window.webContents.emit("zoom-changed", { preventDefault: vi.fn() }, "in");
    adjustWindowZoom(window, 0.5);
    vi.runAllTimers();

    expect({
      zoomLevel: window.webContents.zoomLevel,
      saved: store.save.mock.calls,
    }).toEqual({
      zoomLevel: 1.5,
      saved: [[1], [1.5]],
    });
  });

  it("uses the in-memory zoom level when persistence fails", () => {
    const window = createWindow();
    setupWindowZoom(window);
    store.save.mockImplementation(() => {});

    window.webContents.emit("zoom-changed", { preventDefault: vi.fn() }, "in");
    vi.runAllTimers();
    window.webContents.emit("zoom-changed", { preventDefault: vi.fn() }, "in");
    vi.runAllTimers();

    expect({
      persistedZoomLevel: store.state.zoomLevel,
      zoomLevel: window.webContents.zoomLevel,
      saved: store.save.mock.calls,
    }).toEqual({
      persistedZoomLevel: 0.5,
      zoomLevel: 1.5,
      saved: [[1], [1.5]],
    });
  });

  it("clamps invalid persisted levels before restoring", () => {
    store.get.mockReturnValue(10);
    const window = createWindow();

    restoreWindowZoom(window);

    expect(window.webContents.zoomLevel).toBe(3);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";
import { APP_WINDOW_ARG, QUICK_ASK_WINDOW_ARG } from "../shared/constants";

const { contextBridge, ipcRenderer } = vi.hoisted(() => ({
  contextBridge: { exposeInMainWorld: vi.fn() },
  ipcRenderer: {
    on: vi.fn(),
    sendToHost: vi.fn(),
  },
}));

vi.mock("electron", () => ({
  contextBridge,
  ipcRenderer,
  webUtils: { getPathForFile: vi.fn() },
}));
vi.mock("electron-log/preload", () => ({}));
const { exposeElectronTRPC } = vi.hoisted(() => ({
  exposeElectronTRPC: vi.fn(),
}));
vi.mock("@posthog/electron-trpc/main", () => ({
  exposeElectronTRPC,
}));

import { setupPreload } from "./preload";

describe("preload mode selection", () => {
  beforeEach(() => {
    contextBridge.exposeInMainWorld.mockClear();
    exposeElectronTRPC.mockClear();
    // Each setupPreload registers a once-listener; drop leftovers so the
    // emit below only reaches the branch under test.
    process.removeAllListeners("loaded");
  });

  it("defaults an untagged process to the restricted artifact preload", () => {
    setupPreload([]);

    expect(contextBridge.exposeInMainWorld).not.toHaveBeenCalled();
  });

  it("exposes application APIs only to an explicitly tagged app window", () => {
    setupPreload([APP_WINDOW_ARG]);

    expect(contextBridge.exposeInMainWorld).toHaveBeenCalledWith(
      "electronUtils",
      expect.any(Object),
    );
  });

  it("exposes the quickAsk bridge and the tRPC bridge to a quick-ask window", () => {
    setupPreload([QUICK_ASK_WINDOW_ARG]);

    expect(contextBridge.exposeInMainWorld).toHaveBeenCalledTimes(1);
    expect(contextBridge.exposeInMainWorld).toHaveBeenCalledWith(
      "quickAsk",
      expect.any(Object),
    );
    (process as unknown as { emit(event: string): boolean }).emit("loaded");
    expect(exposeElectronTRPC).toHaveBeenCalledTimes(1);
  });
});

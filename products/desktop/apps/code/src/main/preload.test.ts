import { beforeEach, describe, expect, it, vi } from "vitest";
import { APP_WINDOW_ARG } from "../shared/constants";

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
vi.mock("@posthog/electron-trpc/main", () => ({
  exposeElectronTRPC: vi.fn(),
}));

import { setupPreload } from "./preload";

describe("preload mode selection", () => {
  beforeEach(() => {
    contextBridge.exposeInMainWorld.mockClear();
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
});

import { beforeEach, describe, expect, it, vi } from "vitest";

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

vi.mock("./env", () => ({
  getUserDataDir: () => "/tmp/posthog-code-test",
}));

// Controllable electron-store mock: every Store instance shares `setImpl`,
// so a test can make `.set(...)` throw the way a full disk (ENOSPC) would.
const setImpl = vi.hoisted(() => vi.fn());
vi.mock("electron-store", () => ({
  default: class {
    set = setImpl;
    get = vi.fn();
  },
}));

import {
  saveFullScreenState,
  saveZoomLevel,
  setRestoreFullScreenOnNextLaunch,
} from "./store";

describe("window-state setters", () => {
  beforeEach(() => {
    setImpl.mockReset();
    warn.mockReset();
  });

  it.each([
    ["saveZoomLevel", () => saveZoomLevel(2)],
    ["saveFullScreenState", () => saveFullScreenState(true)],
    [
      "setRestoreFullScreenOnNextLaunch",
      () => setRestoreFullScreenOnNextLaunch(true),
    ],
  ])("%s persists the value through the store", (_name, call) => {
    call();
    expect(setImpl).toHaveBeenCalledTimes(1);
    expect(warn).not.toHaveBeenCalled();
  });

  it.each([
    ["saveZoomLevel", () => saveZoomLevel(2)],
    ["saveFullScreenState", () => saveFullScreenState(true)],
    [
      "setRestoreFullScreenOnNextLaunch",
      () => setRestoreFullScreenOnNextLaunch(true),
    ],
  ])("%s swallows and logs a write failure instead of throwing", (_n, call) => {
    setImpl.mockImplementation(() => {
      throw new Error("ENOSPC: no space left on device");
    });

    expect(() => call()).not.toThrow();
    expect(warn).toHaveBeenCalledTimes(1);
  });
});

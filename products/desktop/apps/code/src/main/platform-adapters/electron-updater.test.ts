import { describe, expect, it, vi } from "vitest";

type Listener = (payload: unknown) => void;

const mockAutoUpdater = vi.hoisted(() => {
  const listeners = new Map<string, Set<Listener>>();
  return {
    listeners,
    on: vi.fn((event: string, listener: Listener) => {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)?.add(listener);
    }),
    off: vi.fn((event: string, listener: Listener) => {
      listeners.get(event)?.delete(listener);
    }),
    emit(event: string, payload: unknown) {
      for (const listener of listeners.get(event) ?? []) listener(payload);
    },
  };
});

vi.mock("inversify", () => ({
  injectable: () => (target: unknown) => target,
}));

vi.mock("electron", () => ({
  app: { isPackaged: true },
}));

vi.mock("electron-log/main", () => ({ default: {} }));

vi.mock("electron-updater", () => ({ autoUpdater: mockAutoUpdater }));

import { ElectronUpdater } from "./electron-updater";

function updateInfo(releaseDate: unknown) {
  return {
    version: "1.2.3",
    releaseDate,
    releaseNotes: null,
    releaseName: null,
    files: [],
  };
}

describe("ElectronUpdater.onUpdateAvailable", () => {
  it.each([
    [
      "a Date parsed from an unquoted channel-file timestamp",
      new Date("2026-06-20T00:00:00.000Z"),
      "2026-06-20T00:00:00.000Z",
    ],
    ["a string", "2026-06-20T00:00:01.000Z", "2026-06-20T00:00:01.000Z"],
    ["an invalid Date", new Date("not a date"), undefined],
    ["a missing value", undefined, undefined],
  ])("reports releaseDate for %s as a string", (_name, input, expected) => {
    const handler = vi.fn();
    const unsubscribe = new ElectronUpdater().onUpdateAvailable(handler);

    mockAutoUpdater.emit("update-available", updateInfo(input));
    unsubscribe();

    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler.mock.calls[0][0].releaseDate).toBe(expected);
  });
});

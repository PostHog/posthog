import {
  createIPCHandler,
  ELECTRON_TRPC_CHANNEL,
} from "@posthog/electron-trpc/main";
import { initTRPC } from "@trpc/server";
import type { BrowserWindow } from "electron";
import { ipcMain } from "electron";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QUICK_ASK_TRPC_ROUTES } from "./quick-ask-trpc";

vi.mock("electron", async () => {
  const { EventEmitter } = await import("node:events");
  return { ipcMain: new EventEmitter() };
});

afterEach(() => {
  ipcMain.removeAllListeners();
});

describe("Quick Ask IPC boundary", () => {
  it.each([
    ["deepLink.openAgentAction", true],
    ["deepLink.openTask", false],
    ["secureStore.set", false],
  ] as const)("gates %s with allowed=%s", async (path, allowed) => {
    const procedure = vi.fn(() => "opened");
    const trpc = initTRPC.create();
    const router = trpc.router({
      deepLink: trpc.router({
        openAgentAction: trpc.procedure.mutation(procedure),
        openTask: trpc.procedure.mutation(procedure),
      }),
      secureStore: trpc.router({
        set: trpc.procedure.mutation(procedure),
      }),
    });
    const webContents = {
      id: 2,
      isDestroyed: () => false,
      on: vi.fn(),
      once: vi.fn(),
    };
    const window = {
      isDestroyed: () => false,
      webContents,
    } as unknown as BrowserWindow;
    const handler = createIPCHandler({ router, windows: [] });
    handler.attachWindow(window, {
      allowedPaths: (route) => QUICK_ASK_TRPC_ROUTES.has(route),
    });
    const event = { sender: webContents, reply: vi.fn() };

    ipcMain.emit(ELECTRON_TRPC_CHANNEL, event, {
      method: "request",
      operation: {
        context: {},
        id: 1,
        input: undefined,
        path,
        type: "mutation",
        signal: undefined,
      },
    });
    await new Promise((resolve) => setImmediate(resolve));

    expect(procedure).toHaveBeenCalledTimes(allowed ? 1 : 0);
    expect(event.reply).toHaveBeenCalledTimes(allowed ? 1 : 0);
  });
});

import * as trpc from "@trpc/server";
import type { BrowserWindow } from "electron";
import { ipcMain } from "electron";
import { describe, expect, test, vi } from "vitest";

import { ELECTRON_TRPC_CHANNEL } from "../../constants";
import { createIPCHandler } from "../createIPCHandler";

vi.mock("electron", async () => {
  const { EventEmitter } = await import("node:events");
  return { ipcMain: new EventEmitter() };
});

const t = trpc.initTRPC.create();
const router = t.router({
  open: t.procedure.query(() => "ok"),
  secret: t.procedure.query(() => "secret"),
});

function fakeWindow(id: number): {
  win: BrowserWindow;
  webContents: { id: number };
} {
  const webContents = {
    id,
    isDestroyed: () => false,
    on: vi.fn(),
    once: vi.fn(),
  };
  return {
    win: {
      isDestroyed: () => false,
      webContents,
    } as unknown as BrowserWindow,
    webContents,
  };
}

function requestFor(path: string, id: number) {
  return {
    method: "request" as const,
    operation: {
      context: {},
      id,
      input: undefined,
      path,
      type: "query" as const,
      signal: undefined,
    },
  };
}

function eventFrom(webContents: unknown) {
  return {
    sender: webContents,
    senderFrame: undefined,
    reply: vi.fn(),
  };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

describe("createIPCHandler sender gating", () => {
  test("answers attached windows and drops unattached senders", async () => {
    const { win, webContents } = fakeWindow(1);
    createIPCHandler({ router, windows: [win as BrowserWindow] });

    const attached = eventFrom(webContents);
    ipcMain.emit(ELECTRON_TRPC_CHANNEL, attached, requestFor("open", 1));
    await flush();
    expect(attached.reply).toHaveBeenCalled();

    // A webContents never attached (another window, a webview) gets nothing.
    const stranger = eventFrom({ id: 99, isDestroyed: () => false });
    ipcMain.emit(ELECTRON_TRPC_CHANNEL, stranger, requestFor("open", 2));
    await flush();
    expect(stranger.reply).not.toHaveBeenCalled();
  });

  test("enforces a window's path allowlist", async () => {
    const main = fakeWindow(1);
    const panel = fakeWindow(2);
    const handler = createIPCHandler({
      router,
      windows: [main.win as BrowserWindow],
    });
    handler.attachWindow(panel.win as BrowserWindow, {
      allowedPaths: (path) => path === "open",
    });

    const allowed = eventFrom(panel.webContents);
    ipcMain.emit(ELECTRON_TRPC_CHANNEL, allowed, requestFor("open", 1));
    await flush();
    expect(allowed.reply).toHaveBeenCalled();

    const blocked = eventFrom(panel.webContents);
    ipcMain.emit(ELECTRON_TRPC_CHANNEL, blocked, requestFor("secret", 2));
    await flush();
    expect(blocked.reply).not.toHaveBeenCalled();

    // The unrestricted main window still reaches every route.
    const mainEvent = eventFrom(main.webContents);
    ipcMain.emit(ELECTRON_TRPC_CHANNEL, mainEvent, requestFor("secret", 3));
    await flush();
    expect(mainEvent.reply).toHaveBeenCalled();
  });
});

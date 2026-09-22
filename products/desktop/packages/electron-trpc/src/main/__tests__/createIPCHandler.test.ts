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
  ticks: t.procedure.subscription(async function* (opts) {
    let n = 0;
    while (!opts.signal?.aborted) {
      yield n++;
      await new Promise((resolve) => setTimeout(resolve, 1));
    }
  }),
});

type WebContentsListener = (...args: unknown[]) => void;

function fakeWindow(id: number): {
  win: BrowserWindow;
  webContents: { id: number };
  emit: (event: string, ...args: unknown[]) => void;
} {
  const listeners = new Map<string, WebContentsListener[]>();
  const webContents = {
    id,
    isDestroyed: () => false,
    on: vi.fn((event: string, listener: WebContentsListener) => {
      listeners.set(event, [...(listeners.get(event) ?? []), listener]);
    }),
    once: vi.fn(),
  };
  return {
    win: {
      isDestroyed: () => false,
      webContents,
    } as unknown as BrowserWindow,
    webContents,
    emit: (event, ...args) => {
      for (const listener of listeners.get(event) ?? []) listener(...args);
    },
  };
}

function requestFor(
  path: string,
  id: number,
  type: "query" | "subscription" = "query",
) {
  return {
    method: "request" as const,
    operation: {
      context: {},
      id,
      input: undefined,
      path,
      type,
      signal: undefined,
    },
  };
}

function replyTypes(reply: ReturnType<typeof vi.fn>): string[] {
  return reply.mock.calls.map(
    ([, message]) =>
      (message as { result?: { type?: string } }).result?.type ?? "error",
  );
}

function eventFrom(webContents: unknown, frameRoutingId?: number) {
  return {
    sender: webContents,
    senderFrame:
      frameRoutingId === undefined ? undefined : { routingId: frameRoutingId },
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

const MAIN_FRAME_ROUTING_ID = 1;

describe("createIPCHandler navigation cleanup", () => {
  test("a navigation that never commits leaves live subscriptions streaming", async () => {
    const { win, webContents, emit } = fakeWindow(1);
    createIPCHandler({ router, windows: [win] });

    const event = eventFrom(webContents, MAIN_FRAME_ROUTING_ID);
    ipcMain.emit(
      ELECTRON_TRPC_CHANNEL,
      event,
      requestFor("ticks", 1, "subscription"),
    );
    await vi.waitFor(() =>
      expect(replyTypes(event.reply)).toEqual(
        expect.arrayContaining(["started", "data"]),
      ),
    );

    // The renderer tried to leave (an external link); will-navigate cancelled
    // it after did-start-navigation had already fired.
    emit("did-start-navigation", {
      isMainFrame: true,
      isSameDocument: false,
      url: "https://example.com/",
      frame: { routingId: MAIN_FRAME_ROUTING_ID },
    });
    const before = event.reply.mock.calls.length;
    await vi.waitFor(() =>
      expect(event.reply.mock.calls.length).toBeGreaterThan(before),
    );
    expect(replyTypes(event.reply)).not.toContain("stopped");
  });

  test.each([
    { frame: "main frame", isMainFrame: true, aborted: 1 },
    { frame: "subframe", isMainFrame: false, aborted: 0 },
  ])(
    "a committed $frame navigation aborts $aborted in-flight operations",
    async ({ isMainFrame, aborted }) => {
      const { win, webContents, emit } = fakeWindow(1);
      const onNavigationCleanup = vi.fn();
      createIPCHandler({ router, windows: [win], onNavigationCleanup });

      const event = eventFrom(webContents, MAIN_FRAME_ROUTING_ID);
      ipcMain.emit(
        ELECTRON_TRPC_CHANNEL,
        event,
        requestFor("ticks", 1, "subscription"),
      );
      await vi.waitFor(() => expect(replyTypes(event.reply)).toContain("data"));

      emit(
        "did-frame-navigate",
        {},
        "file:///app/index.html",
        200,
        "OK",
        isMainFrame,
        4,
        isMainFrame ? MAIN_FRAME_ROUTING_ID + 7 : 12,
      );
      await flush();

      if (aborted > 0) {
        await vi.waitFor(() =>
          expect(replyTypes(event.reply)).toContain("stopped"),
        );
        expect(onNavigationCleanup).toHaveBeenCalledWith({
          webContentsId: 1,
          url: "file:///app/index.html",
          aborted,
        });
      } else {
        expect(replyTypes(event.reply)).not.toContain("stopped");
        expect(onNavigationCleanup).not.toHaveBeenCalled();
      }
    },
  );
});

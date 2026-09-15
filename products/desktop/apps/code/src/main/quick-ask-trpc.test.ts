import {
  createIPCHandler,
  ELECTRON_TRPC_CHANNEL,
} from "@posthog/electron-trpc/main";
import { deepLinkRouter } from "@posthog/host-router/routers/deep-link.router";
import { publicProcedure, router } from "@posthog/host-trpc/trpc";
import { DEEP_LINK_SERVICE } from "@posthog/platform/deep-link";
import type { BrowserWindow } from "electron";
import { ipcMain } from "electron";
import { Container } from "inversify";
import superjson from "superjson";
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
    {
      path: "deepLink.openInboxReport",
      input: { reportId: "report-1" },
      outcome: "opened",
    },
    ...[{}, { reportId: " " }, { reportId: "report-1", kind: "compose" }].map(
      (input) => ({
        path: "deepLink.openInboxReport",
        input,
        outcome: "invalid",
      }),
    ),
    ...[
      { kind: "compose", prompt: "Example task", repo: "posthog/posthog" },
      { kind: "open_space", channel_id: "channel-1" },
      { kind: "open_canvas", channel_id: "channel-1", canvas_id: "canvas-1" },
      { kind: "open_inbox", report_id: "report-1" },
    ].map((action) => ({
      path: "deepLink.openAgentAction",
      input: { action },
      outcome: "blocked",
    })),
    {
      path: "deepLink.open",
      input: { url: "posthog-code://new?prompt=Example" },
      outcome: "blocked",
    },
    { path: "secureStore.set", input: {}, outcome: "blocked" },
  ])(
    "gates $path with $input as $outcome",
    async ({ path, input, outcome }) => {
      const handleUrl = vi.fn(() => true);
      const secureStoreSet = vi.fn();
      const container = new Container();
      container.bind(DEEP_LINK_SERVICE).toConstantValue({
        handleUrl,
        getProtocol: () => "posthog-code-dev",
      });
      const testRouter = router({
        deepLink: deepLinkRouter,
        secureStore: router({
          set: publicProcedure.mutation(secureStoreSet),
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
      const handler = createIPCHandler({
        router: testRouter,
        windows: [],
        createContext: async () => ({ container }),
      });
      handler.attachWindow(window, {
        allowedPaths: (route) => QUICK_ASK_TRPC_ROUTES.has(route),
      });
      const event = { sender: webContents, reply: vi.fn() };

      ipcMain.emit(ELECTRON_TRPC_CHANNEL, event, {
        method: "request",
        operation: {
          context: {},
          id: 1,
          input: superjson.serialize(input),
          path,
          type: "mutation",
          signal: undefined,
        },
      });
      await new Promise((resolve) => setImmediate(resolve));

      expect(secureStoreSet).not.toHaveBeenCalled();
      if (outcome === "opened") {
        expect(handleUrl).toHaveBeenCalledExactlyOnceWith(
          "posthog-code-dev://inbox/report-1",
        );
        expect(event.reply).toHaveBeenCalledExactlyOnceWith(
          ELECTRON_TRPC_CHANNEL,
          { id: 1, result: { type: "data", data: superjson.serialize(true) } },
        );
      } else {
        expect(handleUrl).not.toHaveBeenCalled();
        if (outcome === "blocked") {
          expect(event.reply).not.toHaveBeenCalled();
        } else {
          expect(event.reply).toHaveBeenCalledExactlyOnceWith(
            ELECTRON_TRPC_CHANNEL,
            expect.objectContaining({
              error: expect.objectContaining({
                json: expect.objectContaining({
                  data: expect.objectContaining({ code: "BAD_REQUEST" }),
                }),
              }),
            }),
          );
        }
      }
    },
  );
});

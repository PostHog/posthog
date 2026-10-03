import type { AnyTRPCRouter, inferRouterContext } from "@trpc/server";
import type { BrowserWindow, IpcMainEvent } from "electron";
import { ipcMain } from "electron";

import { ELECTRON_TRPC_CHANNEL } from "../constants";
import type { ETRPCRequest } from "../types";
import { handleIPCMessage } from "./handleIPCMessage";
import type { CreateContextOptions, OnProcedureError } from "./types";

type MaybePromise<TType> = Promise<TType> | TType;

const getInternalId = (event: IpcMainEvent, request: ETRPCRequest) => {
  const messageId =
    request.method === "request" ? request.operation.id : request.id;
  return `${event.sender.id}-${event.senderFrame?.routingId ?? 0}:${messageId}`;
};

export interface AttachWindowOptions {
  /**
   * Restricts the window to a subset of procedure paths (e.g. a narrow
   * bridge for an auxiliary window). Requests outside the set are dropped
   * before they reach the router. Subscription stops and operation cancels
   * always pass: they only touch the sender's own operations.
   */
  allowedPaths?: (path: string) => boolean;
}

export interface NavigationCleanup {
  webContentsId: number;
  url: string;
  /** In-flight operations (queries, mutations, subscriptions) aborted. */
  aborted: number;
}

export type OnNavigationCleanup = (cleanup: NavigationCleanup) => void;

class IPCHandler<TRouter extends AnyTRPCRouter> {
  #windows: BrowserWindow[] = [];
  #pathFilters: Map<number, (path: string) => boolean> = new Map();
  #operations: Map<string, AbortController> = new Map();
  #listener: (event: IpcMainEvent, request: ETRPCRequest) => void;
  #onNavigationCleanup: OnNavigationCleanup | undefined;

  constructor({
    createContext,
    router,
    windows = [],
    onError,
    onNavigationCleanup,
  }: {
    createContext?: (
      opts: CreateContextOptions,
    ) => MaybePromise<inferRouterContext<TRouter>>;
    router: TRouter;
    windows?: BrowserWindow[];
    onError?: OnProcedureError;
    onNavigationCleanup?: OnNavigationCleanup;
  }) {
    this.#onNavigationCleanup = onNavigationCleanup;
    for (const win of windows) {
      this.attachWindow(win);
    }

    this.#listener = (event: IpcMainEvent, request: ETRPCRequest) => {
      // Only attached windows get answers: the channel is a global ipcMain
      // listener, so without this any webContents in the app could reach
      // the full router.
      if (!this.#allows(event, request)) {
        console.warn(
          "electron-trpc: dropped request from unauthorized sender",
          request.method === "request"
            ? request.operation.path
            : request.method,
        );
        return;
      }
      handleIPCMessage({
        router,
        createContext,
        internalId: getInternalId(event, request),
        event,
        message: request,
        operations: this.#operations,
        onError,
      });
    };
    ipcMain.on(ELECTRON_TRPC_CHANNEL, this.#listener);
  }

  #allows(event: IpcMainEvent, request: ETRPCRequest): boolean {
    const attached = this.#windows.some(
      (win) => !win.isDestroyed() && win.webContents === event.sender,
    );
    if (!attached) return false;
    // Stops and cancels are keyed by the sender's own internal id, so they
    // can only ever abort that sender's operations.
    if (request.method !== "request") return true;
    const filter = this.#pathFilters.get(event.sender.id);
    return filter ? filter(request.operation.path) : true;
  }

  destroy() {
    ipcMain.removeListener(ELECTRON_TRPC_CHANNEL, this.#listener);
    for (const sub of this.#operations.values()) {
      sub.abort();
    }
    this.#operations.clear();
  }

  attachWindow(win: BrowserWindow, options?: AttachWindowOptions) {
    if (options?.allowedPaths) {
      this.#pathFilters.set(win.webContents.id, options.allowedPaths);
    }
    if (this.#windows.includes(win)) {
      return;
    }

    this.#windows.push(win);
    this.#attachSubscriptionCleanupHandlers(win);
  }

  detachWindow(win: BrowserWindow, webContentsId?: number) {
    this.#windows = this.#windows.filter((w) => w !== win);

    if (win.isDestroyed() && webContentsId === undefined) {
      throw new Error(
        "webContentsId is required when calling detachWindow on a destroyed window",
      );
    }

    const senderId = webContentsId ?? win.webContents.id;
    this.#pathFilters.delete(senderId);
    this.#cleanUpSubscriptions({
      webContentsId: senderId,
    });
  }

  #cleanUpSubscriptions({ webContentsId }: { webContentsId: number }): number {
    let aborted = 0;
    for (const [key, sub] of this.#operations.entries()) {
      if (key.startsWith(`${webContentsId}-`)) {
        sub.abort();
        this.#operations.delete(key);
        aborted += 1;
      }
    }
    return aborted;
  }

  // Operations belong to the document that issued them, so they are torn down
  // once a main-frame navigation has committed and that document is gone. The
  // commit fires before the new document can send its first request, so
  // sweeping every operation of the webContents here never touches the new
  // document's work. Sweeping earlier, on `did-start-navigation`, is wrong:
  // that fires before `will-navigate`, so a navigation the app cancels there
  // (an external link opened in the browser) would still abort every live
  // subscription while the document stays on screen, with no error the
  // renderer could react to. Subframes never issue operations, so their
  // navigations need no cleanup.
  #attachSubscriptionCleanupHandlers(win: BrowserWindow) {
    const webContentsId = win.webContents.id;
    win.webContents.on(
      "did-frame-navigate",
      (_event, url, _httpResponseCode, _httpStatusText, isMainFrame) => {
        if (!isMainFrame) return;
        const aborted = this.#cleanUpSubscriptions({ webContentsId });
        this.#onNavigationCleanup?.({ webContentsId, url, aborted });
      },
    );
    win.webContents.on("destroyed", () => {
      this.detachWindow(win, webContentsId);
    });
  }
}

let currentHandler: IPCHandler<AnyTRPCRouter> | null = null;

export const createIPCHandler = <TRouter extends AnyTRPCRouter>({
  createContext,
  router,
  windows = [],
  onError,
  onNavigationCleanup,
}: {
  createContext?: (
    opts: CreateContextOptions,
  ) => Promise<inferRouterContext<TRouter>>;
  router: TRouter;
  windows?: Electron.BrowserWindow[];
  onError?: OnProcedureError;
  onNavigationCleanup?: OnNavigationCleanup;
}) => {
  if (currentHandler) {
    currentHandler.destroy();
  }
  currentHandler = new IPCHandler({
    createContext,
    router,
    windows,
    onError,
    onNavigationCleanup,
  });
  return currentHandler;
};

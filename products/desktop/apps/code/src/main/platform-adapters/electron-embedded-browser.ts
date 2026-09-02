import type {
  EmbeddedBrowserBounds,
  EmbeddedBrowserCreateOptions,
  EmbeddedBrowserEvent,
  EmbeddedBrowserPageState,
  IEmbeddedBrowser,
} from "@posthog/platform/embedded-browser";
import { MAIN_WINDOW_SERVICE } from "@posthog/platform/main-window";
import { TypedEventEmitter } from "@posthog/shared";
import { app, session, shell, WebContentsView } from "electron";
import { inject, injectable } from "inversify";
import { logger } from "../utils/logger";
import type { ElectronMainWindow } from "./electron-main-window";

const log = logger.scope("embedded-browser");

/**
 * A separate persistent partition from the app's own session (`persist:main`):
 * pages the user browses never see the app's cookies, and their logins
 * survive app restarts.
 */
const PARTITION = "persist:embedded-browser";

type Events = { event: EmbeddedBrowserEvent };

function isWebUrl(raw: string): boolean {
  try {
    const url = new URL(raw);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

/**
 * A standard-Chrome user agent for embedded pages. Identity providers
 * (notably Google) reject OAuth from anything that identifies as an embedded
 * webview — the default UA carries `Electron/…` and the app token, which
 * triggers `disallowed_useragent`. Stripping those tokens leaves the plain
 * Chrome UA this build actually is.
 */
function browserlikeUserAgent(defaultUserAgent: string): string {
  return defaultUserAgent
    .split(" ")
    .filter(
      (token) =>
        !token.startsWith("Electron/") &&
        !token.toLowerCase().includes("posthog"),
    )
    .join(" ");
}

const GUEST_WEB_PREFERENCES = {
  sandbox: true,
  contextIsolation: true,
  nodeIntegration: false,
  partition: PARTITION,
} as const;

/**
 * Desktop implementation of the embedded browser: one `WebContentsView` per
 * view id, attached to the single main window. The view paints natively ABOVE
 * the renderer, so the renderer drives bounds and visibility over tRPC —
 * nothing in the DOM can cover the view.
 *
 * Security posture: fully sandboxed guest with no preload and no Node, its
 * own cookie partition (never `persist:main`), http(s)-only navigation, and
 * all permission requests (camera, mic, geolocation, …) denied.
 */
@injectable()
export class ElectronEmbeddedBrowser
  extends TypedEventEmitter<Events>
  implements IEmbeddedBrowser
{
  private readonly views = new Map<string, WebContentsView>();
  private sessionHardened = false;

  constructor(
    @inject(MAIN_WINDOW_SERVICE)
    private readonly mainWindow: ElectronMainWindow,
  ) {
    super();
    this.setMaxListeners(0);
  }

  async create(options: EmbeddedBrowserCreateOptions): Promise<void> {
    const existing = this.views.get(options.viewId);
    if (existing && !existing.webContents.isDestroyed()) {
      // Re-opening a kept-alive view (tab switch back): re-glue and re-show
      // it exactly where the user left it. Never navigate here — options.url
      // is a persisted snapshot that lags the live page, so "restoring" it
      // would yank an in-progress flow (a multi-step login, a checkout) back
      // to a stale page. Explicit navigation goes through navigate().
      this.setBounds(options.viewId, options.bounds);
      existing.setVisible(true);
      this.emitPageState(options.viewId, existing);
      return;
    }
    if (existing) this.views.delete(options.viewId);

    const window = this.mainWindow.getBrowserWindow();
    if (!window) throw new Error("No main window to attach the view to");

    this.hardenSession();
    const view = new WebContentsView({
      webPreferences: GUEST_WEB_PREFERENCES,
    });
    this.views.set(options.viewId, view);
    this.wireEvents(options.viewId, view);
    window.contentView.addChildView(view);
    this.setBounds(options.viewId, options.bounds);

    try {
      await view.webContents.loadURL(options.url);
    } catch (error) {
      // Load failures (bad host, offline) keep the view alive — the
      // load-failed event lets the UI explain, and the user can retry from
      // the URL bar.
      log.warn("initial load failed", { url: options.url, error });
    }
  }

  async navigate(viewId: string, url: string): Promise<void> {
    const view = this.mustGet(viewId);
    try {
      await view.webContents.loadURL(url);
    } catch (error) {
      log.warn("navigation failed", { url, error });
      this.emitPageState(viewId, view);
    }
  }

  goBack(viewId: string): void {
    this.views.get(viewId)?.webContents.navigationHistory.goBack();
  }

  goForward(viewId: string): void {
    this.views.get(viewId)?.webContents.navigationHistory.goForward();
  }

  reload(viewId: string): void {
    this.views.get(viewId)?.webContents.reload();
  }

  setBounds(viewId: string, bounds: EmbeddedBrowserBounds): void {
    const view = this.views.get(viewId);
    const window = this.mainWindow.getBrowserWindow();
    if (!view || !window) return;
    // The renderer reports CSS pixels; the window may be zoomed (Cmd+/-), so
    // scale by the host page's zoom factor to land on real window coordinates.
    const zoom = window.webContents.getZoomFactor();
    view.setBounds({
      x: Math.round(bounds.x * zoom),
      y: Math.round(bounds.y * zoom),
      width: Math.max(0, Math.round(bounds.width * zoom)),
      height: Math.max(0, Math.round(bounds.height * zoom)),
    });
  }

  setVisible(viewId: string, visible: boolean): void {
    this.views.get(viewId)?.setVisible(visible);
  }

  openDevTools(viewId: string): void {
    this.views.get(viewId)?.webContents.openDevTools({ mode: "detach" });
  }

  async destroy(viewId: string): Promise<void> {
    const view = this.views.get(viewId);
    if (!view) return;
    this.views.delete(viewId);
    const window = this.mainWindow.getBrowserWindow();
    window?.contentView.removeChildView(view);
    if (!view.webContents.isDestroyed()) view.webContents.close();
    this.emit("event", { type: "view-destroyed", viewId });
  }

  getPageState(viewId: string): EmbeddedBrowserPageState | null {
    const view = this.views.get(viewId);
    return view ? this.pageState(viewId, view) : null;
  }

  events(signal?: AbortSignal): AsyncIterable<EmbeddedBrowserEvent> {
    return this.toIterable("event", { signal });
  }

  /**
   * Electron approves page permission requests by default. Embedded pages get
   * none: a browser panel has no business granting camera, mic, geolocation,
   * or notifications, and the user has no permission UI to review grants.
   */
  private hardenSession(): void {
    if (this.sessionHardened) return;
    this.sessionHardened = true;
    const guestSession = session.fromPartition(PARTITION);
    guestSession.setPermissionRequestHandler((_wc, _permission, callback) =>
      callback(false),
    );
    guestSession.setPermissionCheckHandler(() => false);
    // Identity providers (Google) reject OAuth when the request identifies as
    // an embedded webview (`disallowed_useragent`). Three layers because no
    // single one covers everything: the session UA covers views, the header
    // rewrite covers every network request — including a popup's FIRST one,
    // which is already in flight before any per-webContents override can run
    // (did-create-window fires too late for it).
    guestSession.setUserAgent(browserlikeUserAgent(app.userAgentFallback));
    guestSession.webRequest.onBeforeSendHeaders((details, callback) => {
      const headers = details.requestHeaders;
      const userAgent = headers["User-Agent"];
      if (typeof userAgent === "string") {
        headers["User-Agent"] = browserlikeUserAgent(userAgent);
      }
      callback({ requestHeaders: headers });
    });
  }

  private mustGet(viewId: string): WebContentsView {
    const view = this.views.get(viewId);
    if (!view) throw new Error(`Unknown embedded browser view: ${viewId}`);
    return view;
  }

  private pageState(
    viewId: string,
    view: WebContentsView,
  ): EmbeddedBrowserPageState {
    const wc = view.webContents;
    return {
      viewId,
      url: wc.getURL(),
      title: wc.getTitle(),
      canGoBack: wc.navigationHistory.canGoBack(),
      canGoForward: wc.navigationHistory.canGoForward(),
      isLoading: wc.isLoading(),
    };
  }

  private emitPageState(viewId: string, view: WebContentsView): void {
    this.emit("event", {
      type: "page-state",
      state: this.pageState(viewId, view),
    });
  }

  private wireEvents(viewId: string, view: WebContentsView): void {
    const wc = view.webContents;
    const push = () => this.emitPageState(viewId, view);
    wc.on("did-navigate", push);
    wc.on("did-navigate-in-page", push);
    wc.on("page-title-updated", push);
    wc.on("did-start-loading", push);
    wc.on("did-stop-loading", push);

    wc.on(
      "did-fail-load",
      (_event, errorCode, errorDescription, url, isMainFrame) => {
        // -3 is ERR_ABORTED: fired for normal in-flight cancellations (user
        // navigated again, SPA aborts) — not a failure worth surfacing.
        if (!isMainFrame || errorCode === -3) return;
        this.emit("event", {
          type: "load-failed",
          viewId,
          url,
          errorDescription: errorDescription || `Error ${errorCode}`,
        });
        push();
      },
    );
    wc.on("render-process-gone", (_event, details) => {
      this.emit("event", {
        type: "load-failed",
        viewId,
        url: wc.getURL(),
        errorDescription: `The page crashed (${details.reason})`,
      });
    });

    // The guest stays a plain web page: block non-web schemes.
    wc.on("will-navigate", (event, url) => {
      if (!isWebUrl(url)) event.preventDefault();
    });
    // Allow http(s) popups as real (sandboxed, preload-less) child windows on
    // the SAME cookie partition — popup-based SSO (Google sign-in) needs the
    // popup and the page to share a session, so bouncing it to the system
    // browser can never complete the login. Non-web schemes stay denied.
    wc.setWindowOpenHandler(({ url }) => {
      log.info("popup requested", { viewId, url, allowed: isWebUrl(url) });
      if (!isWebUrl(url)) return { action: "deny" };
      return {
        action: "allow",
        overrideBrowserWindowOptions: {
          autoHideMenuBar: true,
          webPreferences: GUEST_WEB_PREFERENCES,
        },
      };
    });
    wc.on("did-create-window", (child) => {
      // Covers navigator.userAgent for scripts inside the popup; the header
      // rewrite above already covers what servers see.
      child.webContents.setUserAgent(
        browserlikeUserAgent(child.webContents.getUserAgent()),
      );
      child.webContents.on("will-navigate", (event, url) => {
        if (!isWebUrl(url)) event.preventDefault();
      });
      // No nested popups from a popup; open anything further externally.
      child.webContents.setWindowOpenHandler(({ url }) => {
        if (isWebUrl(url)) void shell.openExternal(url);
        return { action: "deny" };
      });
    });
  }
}

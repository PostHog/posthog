/**
 * A live embedded browser surface the host paints natively above the shared
 * UI. The renderer owns placement (bounds, visibility) and navigation intent;
 * the host owns the actual web view, its session, and its security posture.
 *
 * Everything crossing this interface is display-ready navigation data — URLs,
 * titles, loading flags. Nothing from the embedded page's content crosses it.
 */

export interface EmbeddedBrowserBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface EmbeddedBrowserCreateOptions {
  viewId: string;
  url: string;
  /** CSS pixels relative to the host window's web contents. */
  bounds: EmbeddedBrowserBounds;
}

export interface EmbeddedBrowserPageState {
  viewId: string;
  url: string;
  title: string;
  canGoBack: boolean;
  canGoForward: boolean;
  isLoading: boolean;
}

export type EmbeddedBrowserEvent =
  | { type: "page-state"; state: EmbeddedBrowserPageState }
  | {
      type: "load-failed";
      viewId: string;
      url: string;
      errorDescription: string;
    }
  | { type: "view-destroyed"; viewId: string };

export interface IEmbeddedBrowser {
  /**
   * Create the view, or re-attach an existing one (a tab the user switched
   * back to). Re-attaching must never re-navigate: the caller's URL is a
   * persisted snapshot that lags the live page.
   */
  create(options: EmbeddedBrowserCreateOptions): Promise<void>;
  navigate(viewId: string, url: string): Promise<void>;
  goBack(viewId: string): void;
  goForward(viewId: string): void;
  reload(viewId: string): void;
  setBounds(viewId: string, bounds: EmbeddedBrowserBounds): void;
  setVisible(viewId: string, visible: boolean): void;
  openDevTools(viewId: string): void;
  destroy(viewId: string): Promise<void>;
  getPageState(viewId: string): EmbeddedBrowserPageState | null;
  events(signal?: AbortSignal): AsyncIterable<EmbeddedBrowserEvent>;
}

export const EMBEDDED_BROWSER = Symbol.for("posthog.platform.embeddedBrowser");

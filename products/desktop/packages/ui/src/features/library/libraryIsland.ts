import type { EmbeddedWebAppConfig } from "@posthog/platform/embedded-web-app";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { track } from "@posthog/ui/shell/analytics";
import {
  EMBED_API_VERSION,
  type EmbedHandle,
  type EmbedHost,
  type EmbedLocation,
  type MountLegacyApp,
} from "./embeddedWebAppContract";
import { useLibraryIslandStore } from "./libraryIslandStore";
import { toLibraryHref, toWebAppLocation } from "./libraryPaths";

export interface LibraryIslandSession {
  /** Changes when the signed-in account changes, which remounts the web app. */
  identity: string;
  backendHost: string;
  getValidAccessToken: () => Promise<string>;
  refreshAccessToken: () => Promise<string>;
  signOut: () => void;
  theme: EmbedHost["theme"];
}

/**
 * The web app mounts once and stays mounted for the life of the window. Leaving Library parks its
 * element in a hidden node instead of unmounting it, so coming back is instant and the app keeps its
 * state. The web app keeps one global kea context, so a second copy on the page is not possible.
 */
class LibraryIsland {
  private element: HTMLDivElement | null = null;
  private parking: HTMLDivElement | null = null;
  private handle: EmbedHandle | null = null;
  private mounting: Promise<void> | null = null;
  private accessToken = "";
  private identity: string | null = null;
  private lastLocation: EmbedLocation = { pathname: "/", search: "", hash: "" };

  mount(
    config: EmbeddedWebAppConfig,
    session: LibraryIslandSession,
  ): Promise<void> {
    if (this.identity !== null && this.identity !== session.identity) {
      this.reset();
    }
    this.mounting ??= this.load(config, session).finally(() => {
      this.mounting = null;
    });
    return this.mounting;
  }

  /** Shows the web app inside `slot`. */
  attach(slot: HTMLElement): void {
    const element = this.ensureElement();
    if (element.parentElement !== slot) {
      slot.appendChild(element);
    }
  }

  /** Hides the web app without unmounting it. */
  detach(): void {
    const element = this.element;
    if (!element) return;
    this.parking ??= createParking();
    this.parking.appendChild(element);
  }

  syncLocation(): void {
    this.handle?.syncLocation();
  }

  setTheme(theme: EmbedHost["theme"]): void {
    this.handle?.setTheme(theme);
  }

  /** Unmounts the web app, for example after sign-out, so the next session starts clean. */
  reset(): void {
    this.handle?.unmount();
    this.handle = null;
    this.element?.remove();
    this.element = null;
    this.accessToken = "";
    this.identity = null;
    this.lastLocation = { pathname: "/", search: "", hash: "" };
    useLibraryIslandStore.getState().setStatus({ state: "idle" });
  }

  private async load(
    config: EmbeddedWebAppConfig,
    session: LibraryIslandSession,
  ): Promise<void> {
    if (this.handle) return;
    const { setStatus } = useLibraryIslandStore.getState();
    setStatus({ state: "loading" });
    const startedAt = performance.now();

    let mountLegacyApp: MountLegacyApp;
    try {
      this.accessToken = await session.getValidAccessToken();
      const module: { mountLegacyApp?: unknown } = await import(
        /* @vite-ignore */ config.moduleUrl
      );
      if (typeof module.mountLegacyApp !== "function") {
        throw new Error("The module does not export mountLegacyApp");
      }
      mountLegacyApp = module.mountLegacyApp as MountLegacyApp;
    } catch {
      setStatus({ state: "failed", reason: "load_failed" });
      track(ANALYTICS_EVENTS.LIBRARY_LOADED, { outcome: "load_failed" });
      return;
    }

    const handle = mountLegacyApp(this.ensureElement(), {
      backendHost: session.backendHost,
      getAccessToken: () => this.accessToken,
      refreshAccessToken: async () => {
        try {
          this.accessToken = await session.refreshAccessToken();
          return this.accessToken;
        } catch {
          return null;
        }
      },
      getLocation: () => this.readLocation(),
      navigate: (url, { replace }) => {
        // A parked web app can still redirect, for example when a request finishes. Following it
        // would pull the user out of Today or Ask, so it waits for the next sync instead.
        if (!this.isAttached()) return;
        void getRouterOrNull()?.navigate({ href: toLibraryHref(url), replace });
      },
      signOut: session.signOut,
      theme: session.theme,
      analytics: config.analytics,
    });

    if (handle.apiVersion !== EMBED_API_VERSION) {
      handle.unmount();
      setStatus({ state: "failed", reason: "version_mismatch" });
      track(ANALYTICS_EVENTS.LIBRARY_LOADED, { outcome: "version_mismatch" });
      return;
    }

    this.handle = handle;
    this.identity = session.identity;
    setStatus({ state: "mounted" });
    track(ANALYTICS_EVENTS.LIBRARY_LOADED, {
      outcome: "mounted",
      duration_ms: Math.round(performance.now() - startedAt),
    });
  }

  // The web app reads its location on every popstate, including a back step taken while Library is
  // parked. Outside Library it gets the last Library location, so it stays where the user left it.
  private readLocation(): EmbedLocation {
    const location = getRouterOrNull()?.history.location;
    const webAppLocation = location
      ? toWebAppLocation({
          pathname: location.pathname,
          search: location.search,
          hash: location.hash,
        })
      : null;
    if (webAppLocation) {
      this.lastLocation = webAppLocation;
    }
    return this.lastLocation;
  }

  private isAttached(): boolean {
    const parent = this.element?.parentElement;
    return !!parent && parent !== this.parking;
  }

  private ensureElement(): HTMLDivElement {
    if (!this.element) {
      this.element = document.createElement("div");
      this.element.className = "h-full w-full";
    }
    return this.element;
  }
}

function createParking(): HTMLDivElement {
  const parking = document.createElement("div");
  parking.hidden = true;
  document.body.appendChild(parking);
  return parking;
}

export const libraryIsland = new LibraryIsland();

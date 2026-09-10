import "reflect-metadata";
// Side effect: registers the web persistence backend for @posthog/ui stores
// before any of the imports below create them.
import "./web-storage";
import "@posthog/ui/styles/globals.css";
import { AUTH_SERVICE } from "@posthog/core/auth/auth.module";
import { boot } from "@posthog/di/contribution";
import { ServiceProvider } from "@posthog/di/react";
import App from "@posthog/ui/shell/App";
import { initializePostHog } from "@posthog/ui/shell/posthogAnalyticsImpl";
import React from "react";
import ReactDOM from "react-dom/client";
import { Providers } from "./Providers";
import { container } from "./web-container";
import {
  completeOAuthCallbackPage,
  OAUTH_CALLBACK_PATH,
} from "./web-oauth-flow";
import { requestPersistentStorage } from "./web-persistent-storage";

if (window.location.pathname === OAUTH_CALLBACK_PATH) {
  // OAuth popup landing: relay code+state to the opener tab and close.
  // Nothing else may run here — restoring a session in the popup could
  // rotate the refresh token out from under the main tab.
  completeOAuthCallbackPage();
} else {
  // Harden the per-device localStorage stores (cloud-workspace map, archived
  // tasks, pins) against automatic browser eviction. Best-effort; see the
  // helper for what it does and doesn't guarantee.
  void requestPersistentStorage((message, ...args) =>
    console.info(`[web-storage] ${message}`, ...args),
  );

  // Initialize posthog-js for product analytics + error tracking (desktop does
  // this in its renderer boot). Gated on a real project key so a placeholder or
  // unset VITE_POSTHOG_API_KEY leaves posthog uninitialized — the bound tracker
  // and analytics service then no-op gracefully rather than firing at a bogus
  // endpoint. In production web builds this also enables posthog-js's automatic
  // unhandled-error/rejection capture and session recording.
  const posthogKey = import.meta.env.VITE_POSTHOG_API_KEY;
  if (typeof posthogKey === "string" && posthogKey.startsWith("phc_")) {
    initializePostHog();
  }

  // Restore any persisted session (desktop does this in main-process
  // bootstrap); flips authState.bootstrapComplete when done.
  void container.get(AUTH_SERVICE).initialize();
  void boot(container);

  const rootElement = document.getElementById("root");
  if (!rootElement) throw new Error("Root element not found");

  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <ServiceProvider container={container}>
        <Providers>
          <App />
        </Providers>
      </ServiceProvider>
    </React.StrictMode>,
  );
}

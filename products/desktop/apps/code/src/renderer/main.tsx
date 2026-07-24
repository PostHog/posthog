import "reflect-metadata";
// Side effect: registers the host (electron-trpc-backed) storage with @posthog/ui.
// Persisted stores hydrate from it once it registers, wherever in the import
// graph they are created.
import "@utils/electronStorage";
// Side effect: composes the renderer container and calls setRootContainer.
// Must precede the updates adapter below, which resolves UPDATES_CLIENT at
// module scope.
import "@renderer/di/container";
// Side effect: drives the updates subscription + toast via the core update store.
import "@renderer/platform-adapters/updates";
// Side effect: attaches window focus/visibility listeners so `focused` is accurate before inbox queries mount.
import "@posthog/ui/shell/rendererWindowFocusStore";
import {
  BootErrorBoundary,
  BootErrorScreen,
} from "@components/BootErrorBoundary";
import { Providers } from "@components/Providers";
import { DevToolbarHost } from "@features/dev-toolbar/DevToolbarHost";
import { preloadHighlighter } from "@pierre/diffs";
import { boot } from "@posthog/di/contribution";
import { assertHostCapabilities } from "@posthog/di/hostCapabilities";
import { ServiceProvider } from "@posthog/di/react";
import App from "@posthog/ui/shell/App";
import { logger } from "@posthog/ui/shell/logger";
import { initializePostHog } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { REQUIRED_HOST_CAPABILITIES } from "@posthog/ui/shell/requiredHostCapabilities";
import { registerDesktopContributions } from "@renderer/desktop-contributions";
import { container } from "@renderer/di/container";
import "@renderer/desktop-services";
import React from "react";
import ReactDOM from "react-dom/client";
import "@posthog/ui/styles/globals.css";

void preloadHighlighter({
  themes: ["github-dark", "github-light"],
  langs: [
    "typescript",
    "tsx",
    "javascript",
    "jsx",
    "json",
    "css",
    "html",
    "markdown",
    "python",
    "ruby",
    "go",
    "rust",
    "shell",
    "yaml",
    "sql",
  ],
});

// HACK(@posthog/hedgehog-mode): The package bundles react-dom 18 code that
// accesses React 18 internals at module scope. React 19 moved these to
// __CLIENT_INTERNALS and removed the old names. Shim the old structure so the
// bundled code doesn't crash on import.
// Remove once hedgehog-mode ships a React 19 compatible build.
{
  const r = React as unknown as Record<string, unknown>;
  if (!r.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED) {
    r.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED = {};
  }
  const internals =
    r.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED as Record<
      string,
      unknown
    >;
  if (!internals.ReactCurrentDispatcher) {
    internals.ReactCurrentDispatcher = { current: null };
  }
  if (!internals.ReactCurrentOwner) {
    internals.ReactCurrentOwner = { current: null };
  }
  if (!internals.ReactDebugCurrentFrame) {
    internals.ReactDebugCurrentFrame = { getCurrentStack: null };
  }
}

document.title = import.meta.env.DEV ? "PostHog (Development)" : "PostHog";

const bootstrapSessionId = window.__posthogBootstrap?.sessionId;
if (bootstrapSessionId) {
  initializePostHog(bootstrapSessionId);
}

const bootLog = logger.scope("renderer-boot");

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("Root element not found");

const root = ReactDOM.createRoot(rootElement);

try {
  registerDesktopContributions();
  // Fail loudly (into BootErrorScreen) if a capability the shared app resolves
  // via service location is unbound, rather than deferring to the first
  // navigation that needs it. The renderer container backs every useService, so
  // all required tokens must resolve here. Shared with the web host.
  assertHostCapabilities(container, REQUIRED_HOST_CAPABILITIES);
  boot(container).catch((error: unknown) => {
    bootLog.error("Renderer boot sequence failed", error);
    // Replaces the mounted tree without running effect cleanup; acceptable
    // because a failed boot leaves the app unusable regardless.
    root.render(<BootErrorScreen error={error} />);
  });

  root.render(
    <React.StrictMode>
      <BootErrorBoundary>
        <ServiceProvider container={container}>
          <Providers>
            <App devToolbar={<DevToolbarHost />} />
          </Providers>
        </ServiceProvider>
      </BootErrorBoundary>
    </React.StrictMode>,
  );
} catch (error) {
  bootLog.error("Renderer failed to start", error);
  root.render(<BootErrorScreen error={error} />);
}

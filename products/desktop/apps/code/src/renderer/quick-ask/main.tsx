// Global styles first so quick-ask.css overrides win at equal specificity.
import "@posthog/ui/styles/globals.css";
import "@posthog/quick-ask/panel/quick-ask.css";
import type { AuthState } from "@posthog/core/auth/schemas";
import { setRootContainer } from "@posthog/di/container";
import { ipcLink } from "@posthog/electron-trpc/renderer";
import { HOST_TRPC_CLIENT } from "@posthog/host-router/client";
import { HostTRPCProvider } from "@posthog/host-router/react";
import type { HostRouter } from "@posthog/host-router/router";
import { QuickAsk } from "@posthog/quick-ask/panel/QuickAsk";
import { getAuthIdentity, useAuthStore } from "@posthog/ui/features/auth/store";
import { ThemeWrapper } from "@posthog/ui/primitives/ThemeWrapper";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createTRPCClient } from "@trpc/client";
import { Container } from "inversify";
import React from "react";
import ReactDOM from "react-dom/client";
import superjson from "superjson";
import { BootErrorBoundary } from "../components/BootErrorBoundary";

// The panel boots only what answer rendering needs: host tRPC (auth tokens,
// external links), react-query, and the theme.
const hostTrpcClient = createTRPCClient<HostRouter>({
  links: [ipcLink({ transformer: superjson })],
});

// Components outside React's tree (openExternalUrl) resolve the host client
// through the shared service locator.
const container = new Container();
container.bind(HOST_TRPC_CLIENT).toConstantValue(hostTrpcClient);
setRootContainer(container);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

// The panel has its own react-query cache and never runs the main window's
// project-switch side effects, so it purges auth-scoped queries itself when
// the identity (region + project) changes. Without this, a chart or preview
// cached in project A would serve under project B for its stale period.
let authIdentity: string | null | undefined;
function applyAuthState(state: AuthState): void {
  const next = getAuthIdentity(state);
  if (authIdentity !== undefined && next !== authIdentity) {
    queryClient.removeQueries({
      predicate: (query) => query.meta?.authScoped === true,
    });
  }
  authIdentity = next;
  useAuthStore.getState().setAuthState(state);
}

// Subscription first so no auth state change is missed while the initial
// query is in flight.
hostTrpcClient.auth.onStateChanged.subscribe(undefined, {
  onData: (state) => applyAuthState(state),
});
void hostTrpcClient.auth.getState
  .query()
  .then((state) => applyAuthState(state))
  .catch(() => {
    // Signed-out rendering is fine; chips fall back to static cards.
  });

// Theme changes made in the main window land in shared localStorage;
// re-reading them keeps this window on the app's theme.
window.addEventListener("storage", (event) => {
  if (event.key === "theme-storage") {
    void useThemeStore.persist.rehydrate();
  }
});

const root = document.getElementById("root");
if (root) {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      {/* A render crash (rich answer content is live data) otherwise unmounts
          the whole panel with no way to close, reset, or retry; the boundary's
          reload boots the window fresh. */}
      <BootErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <HostTRPCProvider
            trpcClient={hostTrpcClient}
            queryClient={queryClient}
          >
            <ThemeWrapper>
              <QuickAsk />
            </ThemeWrapper>
          </HostTRPCProvider>
        </QueryClientProvider>
      </BootErrorBoundary>
    </React.StrictMode>,
  );
}

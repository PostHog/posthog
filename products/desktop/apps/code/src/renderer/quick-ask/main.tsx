// Global styles first so quick-ask.css overrides win at equal specificity.
import "@posthog/ui/styles/globals.css";
import "./quick-ask.css";
import { setRootContainer } from "@posthog/di/container";
import { ipcLink } from "@posthog/electron-trpc/renderer";
import { HOST_TRPC_CLIENT } from "@posthog/host-router/client";
import { HostTRPCProvider } from "@posthog/host-router/react";
import type { HostRouter } from "@posthog/host-router/router";
import { useAuthStore } from "@posthog/ui/features/auth/store";
import { ThemeWrapper } from "@posthog/ui/primitives/ThemeWrapper";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createTRPCClient } from "@trpc/client";
import { Container } from "inversify";
import React from "react";
import ReactDOM from "react-dom/client";
import superjson from "superjson";
import { QuickAsk } from "./QuickAsk";

/**
 * The panel boots a deliberately thin slice of the app: host tRPC (auth
 * tokens, external links) + react-query + the theme. That is exactly what the
 * shared evidence pipeline needs to resolve object tags into live chips and
 * chart cards - no app DI graph, no router, no workspace client.
 */
const hostTrpcClient = createTRPCClient<HostRouter>({
  links: [ipcLink({ transformer: superjson })],
});

// Components outside React's tree (openExternalUrl) resolve the host client
// through the shared service locator.
const container = new Container();
container.bind(HOST_TRPC_CLIENT).toConstantValue(hostTrpcClient);
setRootContainer(container);

// Hydrate the auth store the evidence components read (project id, region,
// tokens). Subscription first so no state change is missed while the initial
// query is in flight.
hostTrpcClient.auth.onStateChanged.subscribe(undefined, {
  onData: (state) => useAuthStore.getState().setAuthState(state),
});
void hostTrpcClient.auth.getState
  .query()
  .then((state) => useAuthStore.getState().setAuthState(state))
  .catch(() => {
    // Signed-out rendering is fine; chips fall back to static cards.
  });

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
});

const root = document.getElementById("root");
if (root) {
  ReactDOM.createRoot(root).render(
    <React.StrictMode>
      <QueryClientProvider client={queryClient}>
        <HostTRPCProvider trpcClient={hostTrpcClient} queryClient={queryClient}>
          {/* The panel's palette is hard-coded dark; pin the theme to match. */}
          <ThemeWrapper appearance="dark">
            <QuickAsk />
          </ThemeWrapper>
        </HostTRPCProvider>
      </QueryClientProvider>
    </React.StrictMode>,
  );
}

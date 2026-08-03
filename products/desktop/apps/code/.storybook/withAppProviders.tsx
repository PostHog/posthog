import { type ServiceContainer, setRootContainer } from "@posthog/di/container";
import { ServiceProvider } from "@posthog/di/react";
import { ipcLink } from "@posthog/electron-trpc/renderer";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { HostTRPCProvider } from "@posthog/host-router/react";
import type { HostRouter } from "@posthog/host-router/router";
import {
  FEATURE_FLAGS,
  type FeatureFlags,
} from "@posthog/ui/features/feature-flags/identifiers";
import { DIFF_WORKER_FACTORY } from "@posthog/ui/shell/diffWorkerHost";
import { IMPERATIVE_QUERY_CLIENT } from "@posthog/ui/shell/queryClient";
import type { Decorator } from "@storybook/react-vite";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { createTRPCClient } from "@trpc/client";
import { Container } from "inversify";
import { useMemo, useRef } from "react";

// A host-agnostic stand-in for the host tRPC client. Components that resolve
// HOST_TRPC_CLIENT from DI get these no-op responses; queries issued through the
// React `useHostTRPC()` context go through the mocked ipc link and simply stay
// pending, which is fine for visual stories.
const noopHostClient = {
  git: {
    getGhStatus: {
      query: async () => ({
        installed: true,
        version: "2.0.0",
        authenticated: true,
        username: "storybook",
        error: null,
      }),
    },
    searchGithubRefs: { query: async () => [] },
    getGithubPullRequest: { query: async () => null },
    getGithubIssue: { query: async () => null },
  },
  fs: {
    listRepoFiles: { query: async () => [] },
    readAbsoluteFile: { query: async () => null },
  },
  os: {
    selectDirectory: { query: async () => null },
    selectAttachments: { query: async () => [] },
    readFileAsDataUrl: { query: async () => null },
    saveClipboardImage: {
      mutate: async () => ({ path: "", name: "", mimeType: "" }),
    },
    saveClipboardText: { mutate: async () => ({ path: "", name: "" }) },
    saveClipboardFile: { mutate: async () => ({ path: "", name: "" }) },
    downscaleImageFile: { mutate: async () => ({ path: "", name: "" }) },
  },
  skills: {
    list: { query: async () => [] },
  },
} as unknown as HostTrpcClient;

// Diffs are computed in a web worker. Storybook has no worker backend, so hand
// out an inert stub: components render, diffs just never resolve.
const stubWorker = {
  postMessage() {},
  terminate() {},
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() {
    return false;
  },
  onmessage: null,
  onmessageerror: null,
  onerror: null,
} as unknown as Worker;

// An inert, infinitely-chainable stand-in for any core service a deep component
// tree resolves that we haven't (and don't need to) wire up for visuals — e.g.
// the external-apps service behind a "open in editor" button. Property access
// yields another stub and calls return one, so `service.foo().bar` never throws.
// Methods invoked from event handlers are simply no-ops in Storybook.
// `then` must be undefined: otherwise the stub is thenable and `await
// service.foo()` would never settle (the stubbed `then` never calls resolve).
function inertServiceStub(): unknown {
  const target = () => undefined;
  return new Proxy(target, {
    get: (_target, prop) => (prop === "then" ? undefined : inertServiceStub()),
    apply: () => inertServiceStub(),
  });
}

// A ServiceContainer that resolves the few services stories genuinely need and
// falls back to an inert stub for everything else. `isBound` stays truthful so
// `useServiceOptional` still returns null for unbound optional services.
// Stubs are cached per service id: hooks use the resolved service as an
// effect/memo dependency (e.g. useFeatureFlag), and a fresh Proxy per `get`
// re-fires those effects every render — an infinite setState loop.
function storyContainer(bindings: Container): ServiceContainer {
  const stubs = new Map<unknown, unknown>();
  const stubFor = (id: unknown) => {
    let stub = stubs.get(id);
    if (!stub) {
      stub = inertServiceStub();
      stubs.set(id, stub);
    }
    return stub;
  };
  return {
    get: (id) => (bindings.isBound(id) ? bindings.get(id) : stubFor(id)),
    getAll: (id) => (bindings.isBound(id) ? bindings.getAll(id) : []),
    isBound: (id) => bindings.isBound(id),
    bind: (id) => bindings.bind(id),
  } as unknown as ServiceContainer;
}

/**
 * Wraps every story in the same provider stack the renderer mounts at boot:
 * a QueryClient, the host tRPC context, the DI service container, and a minimal
 * TanStack Router. Components that reach for any of these (useHostTRPC,
 * useService, useRouterState, …) then render in Storybook instead of throwing
 * "must be used within a <Provider>".
 */
interface ProviderStack {
  queryClient: QueryClient;
  hostTrpcClient: ReturnType<typeof createTRPCClient<HostRouter>>;
  container: ServiceContainer;
}

function createProviderStack(): ProviderStack {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  });

  const hostTrpcClient = createTRPCClient<HostRouter>({
    links: [ipcLink()],
  });

  const bindings = new Container();
  bindings
    .bind<HostTrpcClient>(HOST_TRPC_CLIENT)
    .toConstantValue(noopHostClient);
  bindings.bind(IMPERATIVE_QUERY_CLIENT).toConstantValue(queryClient);
  bindings.bind(DIFF_WORKER_FACTORY).toConstantValue(() => stubWorker);
  // Real (not inert-proxy) flags: isEnabled must return an actual boolean, or
  // every flag reads as enabled and useFeatureFlag's state never settles.
  bindings.bind<FeatureFlags>(FEATURE_FLAGS).toConstantValue({
    isEnabled: () => false,
    onFlagsLoaded: () => () => {},
  });
  const container = storyContainer(bindings);
  setRootContainer(container);

  return { queryClient, hostTrpcClient, container };
}

export const withAppProviders: Decorator = (Story) => {
  // The provider singletons don't depend on the story; build them once per
  // mount. Lazy ref rather than useMemo: setRootContainer mutates a global, and
  // Strict Mode double-invokes useMemo initializers, which would build (and
  // globally register) a container that React then abandons. The ref object is
  // stable across the double render, so this runs exactly once.
  const stackRef = useRef<ProviderStack | null>(null);
  if (stackRef.current === null) {
    stackRef.current = createProviderStack();
  }
  const { queryClient, hostTrpcClient, container } = stackRef.current;

  // The router's root route renders the story, so it's keyed on the story.
  const router = useMemo(
    () =>
      createRouter({
        routeTree: createRootRoute({ component: () => <Story /> }),
        history: createMemoryHistory({ initialEntries: ["/"] }),
      }),
    [Story],
  );

  return (
    <QueryClientProvider client={queryClient}>
      <HostTRPCProvider trpcClient={hostTrpcClient} queryClient={queryClient}>
        <ServiceProvider container={container}>
          <RouterProvider router={router} />
        </ServiceProvider>
      </HostTRPCProvider>
    </QueryClientProvider>
  );
};

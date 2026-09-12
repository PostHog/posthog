import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const queryKey = (procedure: string, id: string) => [
  ["dashboards", procedure],
  { input: { id }, type: "query" },
];

const fetchView = vi.hoisted(() => vi.fn());

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    dashboards: {
      view: {
        queryOptions: ({ id }: { id: string }, options: object) => ({
          ...options,
          queryKey: queryKey("view", id),
          queryFn: () => fetchView(id),
        }),
      },
      get: { queryKey: ({ id }: { id: string }) => queryKey("get", id) },
      builds: { queryKey: ({ id }: { id: string }) => queryKey("builds", id) },
      source: { queryKey: ({ id }: { id: string }) => queryKey("source", id) },
      layout: { queryKey: ({ id }: { id: string }) => queryKey("layout", id) },
    },
  }),
}));

import {
  ANONYMOUS_AUTH_STATE,
  useAuthStore,
} from "@posthog/ui/features/auth/store";
import { usePrimeCanvasView } from "./useDashboards";

const VIEW = {
  record: { id: "canvas-1", publishedBuildId: null },
  currentVersionId: null,
  publishedBuild: null,
  hasActiveBuild: false,
  source: { files: {} },
  layout: null,
  componentLifecycles: {},
};

function signIn(projectId: number): void {
  useAuthStore.getState().setAuthState({
    ...ANONYMOUS_AUTH_STATE,
    status: "authenticated",
    bootstrapComplete: true,
    cloudRegion: "us",
    currentProjectId: projectId,
  });
}

describe("usePrimeCanvasView", () => {
  let queryClient: QueryClient;

  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  const prime = () =>
    renderHook(() => usePrimeCanvasView(), { wrapper }).result.current;

  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    signIn(1);
  });

  it("leaves nothing behind for the next account to read", async () => {
    fetchView.mockResolvedValue(VIEW);

    prime()("canvas-1");
    await waitFor(() =>
      expect(queryClient.getQueryData(queryKey("get", "canvas-1"))).toEqual(
        VIEW.record,
      ),
    );

    // What the sign-out path runs: everything the signed-in account fetched.
    queryClient.removeQueries({
      predicate: (query) => query.meta?.authScoped === true,
    });

    expect(
      queryClient.getQueryData(queryKey("view", "canvas-1")),
    ).toBeUndefined();
  });

  it("drops a response that arrives after the project changed", async () => {
    let resolveView: (value: typeof VIEW) => void = () => {};
    fetchView.mockReturnValue(
      new Promise<typeof VIEW>((resolve) => {
        resolveView = resolve;
      }),
    );

    prime()("canvas-1");
    await waitFor(() => expect(fetchView).toHaveBeenCalled());
    signIn(2);
    resolveView(VIEW);
    // The seeding runs off the same response the view cache settles from, so
    // wait for that and then let the seeding continuation have its turn.
    await waitFor(() =>
      expect(queryClient.getQueryData(queryKey("view", "canvas-1"))).toEqual(
        VIEW,
      ),
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(
      queryClient.getQueryData(queryKey("get", "canvas-1")),
    ).toBeUndefined();
  });
});

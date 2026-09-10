import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const HOME_KEY = ["dashboards", "home"];

const mocks = vi.hoisted(() => ({ home: vi.fn() }));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    dashboards: {
      home: {
        queryOptions: (_input: unknown, options: Record<string, unknown>) => ({
          queryKey: HOME_KEY,
          queryFn: () => mocks.home(),
          ...options,
        }),
      },
    },
  }),
}));

// The home canvas itself is another surface's concern; this file is about the
// query that resolves which canvas Home shows.
vi.mock("./GridCanvasView", () => ({ GridCanvasView: () => null }));

import { HomeView } from "./HomeView";

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("HomeView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
  });

  // Home's provisioning query takes no input, so every account on the machine
  // shares one cache key, and staleTime Infinity means nothing refetches it. The
  // auth-scoped meta is what makes a logout, org switch, or project switch evict
  // it — without it the next user's Home renders the previous user's personal
  // canvas.
  it("caches the home canvas under a query an account change evicts", async () => {
    mocks.home.mockResolvedValue({ id: "canvas-1", name: "Home" });

    render(<HomeView />, { wrapper });
    await screen.findByText("Home");
    expect(queryClient.getQueryData(HOME_KEY)).toMatchObject({
      id: "canvas-1",
    });

    // The predicate clearAuthScopedQueries runs on every account change.
    queryClient.removeQueries({
      predicate: (query) => query.meta?.authScoped === true,
    });

    expect(queryClient.getQueryData(HOME_KEY)).toBeUndefined();
  });
});

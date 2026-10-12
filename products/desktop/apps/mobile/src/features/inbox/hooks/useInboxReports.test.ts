import type {
  SignalReport,
  SignalReportsQueryParams,
  SignalReportsResponse,
} from "@posthog/shared/domain-types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getCurrentUser, getSignalReports, getAvailableSuggestedReviewers } =
  vi.hoisted(() => ({
    getCurrentUser: vi.fn<() => Promise<{ uuid: string }>>(),
    getSignalReports:
      vi.fn<
        (params: SignalReportsQueryParams) => Promise<SignalReportsResponse>
      >(),
    getAvailableSuggestedReviewers: vi.fn(async (_query?: string) => ({
      results: [],
      count: 0,
    })),
  }));

vi.mock("@/features/auth", () => ({
  useAuthStore: () => ({ projectId: 1, oauthAccessToken: "token" }),
  userQueryOptions: {
    queryKey: ["user", "me"],
    queryFn: getCurrentUser,
    staleTime: 5 * 60 * 1000,
  },
}));

vi.mock("@/lib/posthogApiClient", () => ({
  getPostHogApiClient: () => ({
    getAvailableSuggestedReviewers,
    getSignalReports,
  }),
}));

import { useInboxFilterStore } from "../stores/inboxFilterStore";
import {
  getReportsNextPageParam,
  useAvailableSuggestedReviewers,
  useInboxReports,
} from "./useInboxReports";

const renders: { renderer: ReactTestRenderer; client: QueryClient }[] = [];

afterEach(async () => {
  for (const { renderer, client } of renders.splice(0)) {
    await act(async () => renderer.unmount());
    client.clear();
  }
  vi.clearAllMocks();
});

function page(count: number, resultCount: number): SignalReportsResponse {
  return {
    count,
    results: Array.from({ length: resultCount }, () => ({}) as SignalReport),
  };
}

describe("getReportsNextPageParam", () => {
  it.each([
    {
      name: "offset after the first page when more remain",
      pages: [page(250, 100)],
      expected: 100,
    },
    {
      name: "offset after later pages when more remain",
      pages: [page(250, 100), page(250, 100)],
      expected: 200,
    },
    {
      name: "undefined once every report is loaded",
      pages: [page(150, 100), page(150, 50)],
      expected: undefined,
    },
    {
      name: "undefined when the first page already holds everything",
      pages: [page(40, 40)],
      expected: undefined,
    },
  ])("returns the $name", ({ pages, expected }) => {
    const lastPage = pages[pages.length - 1];
    expect(getReportsNextPageParam(lastPage, pages)).toBe(expected);
  });
});

async function renderHook<T>(hook: () => T) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  let result: T;
  function Wrapper() {
    result = hook();
    return null;
  }
  await act(async () => {
    const renderer = create(
      createElement(QueryClientProvider, { client }, createElement(Wrapper)),
    );
    renders.push({ renderer, client });
  });
  return {
    get result() {
      return result;
    },
  };
}

describe("useAvailableSuggestedReviewers", () => {
  it.each([
    { name: "forwards a trimmed query", query: "  alice  ", expected: "alice" },
    {
      name: "omits a whitespace-only query",
      query: "   ",
      expected: undefined,
    },
    { name: "omits an undefined query", query: undefined, expected: undefined },
  ])("$name to the server", async ({ query, expected }) => {
    await renderHook(() => useAvailableSuggestedReviewers({ query }));
    expect(getAvailableSuggestedReviewers).toHaveBeenCalledWith(expected);
  });
});

describe("useInboxReports", () => {
  beforeEach(() => {
    useInboxFilterStore.getState().resetFilters();
    getCurrentUser.mockReset();
    getSignalReports.mockReset().mockResolvedValue(page(0, 0));
  });

  it("retries the current user before requesting default-scope reports", async () => {
    getCurrentUser.mockRejectedValueOnce(new Error("User lookup failed"));
    const hook = await renderHook(() => useInboxReports());
    await vi.waitFor(() => {
      expect(hook.result.error).toBe("User lookup failed");
    });
    expect(getSignalReports).not.toHaveBeenCalled();

    let resolveUser!: (user: { uuid: string }) => void;
    getCurrentUser.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveUser = resolve;
      }),
    );
    let retry!: ReturnType<typeof hook.result.refetch>;
    await act(async () => {
      retry = hook.result.refetch();
    });
    expect(getCurrentUser).toHaveBeenCalledTimes(2);
    expect(getSignalReports).not.toHaveBeenCalled();

    await act(async () => {
      resolveUser({ uuid: "me" });
      await retry;
    });
    expect(getSignalReports).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ suggested_reviewers: "me", offset: 0 }),
    );
    await vi.waitFor(() => expect(hook.result.error).toBeNull());
    expect(hook.result.isReviewerScoped).toBe(true);
  });

  it.each([
    { reviewers: [], expected: undefined, scoped: false },
    { reviewers: ["teammate"], expected: "teammate", scoped: true },
  ])(
    "loads an explicit selection $reviewers without a user lookup",
    async ({ reviewers, expected, scoped }) => {
      useInboxFilterStore.getState().setSuggestedReviewerFilter(reviewers);
      const hook = await renderHook(() => useInboxReports());
      await vi.waitFor(() => {
        expect(getSignalReports).toHaveBeenCalledExactlyOnceWith(
          expect.objectContaining({ suggested_reviewers: expected }),
        );
      });
      expect(getCurrentUser).not.toHaveBeenCalled();
      expect(hook.result.isReviewerScoped).toBe(scoped);
    },
  );

  it("does not show cached project reports while the default user loads", async () => {
    useInboxFilterStore.getState().setSuggestedReviewerFilter([]);
    getSignalReports.mockResolvedValueOnce(page(1, 1));
    const hook = await renderHook(() => useInboxReports());
    await vi.waitFor(() => expect(hook.result.reports).toHaveLength(1));

    let resolveUser!: (user: { uuid: string }) => void;
    getCurrentUser.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveUser = resolve;
      }),
    );
    await act(async () => useInboxFilterStore.getState().resetFilters());
    expect(hook.result.reports).toEqual([]);
    expect(hook.result.isLoading).toBe(true);
    expect(hook.result.isReviewerScoped).toBe(true);
    expect(getSignalReports).toHaveBeenCalledTimes(1);

    await act(async () => resolveUser({ uuid: "me" }));
    await vi.waitFor(() => {
      expect(getSignalReports).toHaveBeenLastCalledWith(
        expect.objectContaining({ suggested_reviewers: "me" }),
      );
      expect(hook.result.isLoading).toBe(false);
    });
  });
});

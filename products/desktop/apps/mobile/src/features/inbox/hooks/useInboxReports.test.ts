import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/features/auth", () => ({
  useAuthStore: () => ({ projectId: 1, oauthAccessToken: "token" }),
}));

const getAvailableSuggestedReviewers = vi.fn(async (_query?: string) => ({
  results: [],
  count: 0,
}));
vi.mock("../api", () => ({
  getAvailableSuggestedReviewers: (query?: string) =>
    getAvailableSuggestedReviewers(query),
}));

import type { SignalReport, SignalReportsResponse } from "../types";
import {
  getReportsNextPageParam,
  useAvailableSuggestedReviewers,
} from "./useInboxReports";

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

async function renderHook(query?: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper() {
    useAvailableSuggestedReviewers({ query });
    return null;
  }
  await act(async () => {
    create(
      createElement(QueryClientProvider, { client }, createElement(Wrapper)),
    );
    await Promise.resolve();
  });
}

describe("useAvailableSuggestedReviewers", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it.each([
    { name: "forwards a trimmed query", query: "  alice  ", expected: "alice" },
    {
      name: "omits a whitespace-only query",
      query: "   ",
      expected: undefined,
    },
    { name: "omits an undefined query", query: undefined, expected: undefined },
  ])("$name to the server", async ({ query, expected }) => {
    await renderHook(query);
    expect(getAvailableSuggestedReviewers).toHaveBeenCalledWith(expected);
  });
});

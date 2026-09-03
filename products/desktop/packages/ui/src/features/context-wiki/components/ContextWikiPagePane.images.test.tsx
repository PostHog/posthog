import { Theme } from "@radix-ui/themes";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

// MarkdownRenderer's chart cards resolve data through the app shell's query
// client; stub it so the real renderer mounts here.
vi.mock("../../../hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({
    isPending: true,
    isError: false,
    isFetched: false,
    data: undefined,
  }),
}));

const hoisted = vi.hoisted(() => ({
  page: {
    path: "AGENTS.md",
    content: "![internal service](http://127.0.0.1/action)",
    head_sha: "head-1",
  } as { path: string; content: string; head_sha: string } | null,
}));

vi.mock("../hooks/useContextWiki", () => ({
  useContextWikiPage: () => ({
    data: hoisted.page,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
  useContextWikiPageMutation: () => ({
    mutate: vi.fn(),
    error: null,
    isPending: false,
    reset: vi.fn(),
  }),
}));

// The real client pulls in @posthog/shared, which this package's vitest config
// does not resolve; the pane only needs these two error classes for instanceof.
vi.mock("@posthog/api-client/posthog-client", () => ({
  ContextWikiConflictError: class ContextWikiConflictError extends Error {},
  ContextWikiLintError: class ContextWikiLintError extends Error {},
}));

import { ContextWikiPagePane } from "./ContextWikiPagePane";

describe("ContextWikiPagePane markdown", () => {
  it("does not load remote images embedded in a wiki page", () => {
    const html = renderToStaticMarkup(
      <Theme>
        <ContextWikiPagePane path="AGENTS.md" />
      </Theme>,
    );

    expect(html).toContain("Remote image blocked: internal service");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("http://127.0.0.1/action");
  });
});

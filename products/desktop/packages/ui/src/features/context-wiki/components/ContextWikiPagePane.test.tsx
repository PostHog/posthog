import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ContextWikiPagePane } from "./ContextWikiPagePane";

const hoisted = vi.hoisted(() => ({
  page: {
    path: "AGENTS.md",
    content: "original content",
    head_sha: "head-1",
  } as { path: string; content: string; head_sha: string } | null,
  mutate: vi.fn(),
  reset: vi.fn(),
  refetch: vi.fn(),
}));

vi.mock("../hooks/useContextWiki", () => ({
  useContextWikiPage: () => ({
    data: hoisted.page,
    isLoading: false,
    error: null,
    refetch: hoisted.refetch,
  }),
  useContextWikiPageMutation: () => ({
    mutate: hoisted.mutate,
    error: null,
    isPending: false,
    reset: hoisted.reset,
  }),
}));

vi.mock("@posthog/ui/features/editor/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

// The real client pulls in @posthog/shared, which this package's vitest config
// does not resolve. This pane only needs the two error classes for the
// instanceof checks on a failed save, which this test does not exercise.
vi.mock("@posthog/api-client/posthog-client", () => ({
  ContextWikiConflictError: class ContextWikiConflictError extends Error {},
  ContextWikiLintError: class ContextWikiLintError extends Error {},
}));

describe("ContextWikiPagePane", () => {
  it("saves against the head the draft was seeded from, not a head that moved under it mid-edit", async () => {
    hoisted.page = {
      path: "AGENTS.md",
      content: "original content",
      head_sha: "head-1",
    };
    hoisted.mutate.mockClear();
    const user = userEvent.setup();

    const { rerender } = render(<ContextWikiPagePane path="AGENTS.md" />);

    await user.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(
      screen.getByPlaceholderText("Write markdown for this page…"),
      { target: { value: "my local edits" } },
    );

    // An agent lands a commit in the background; a focus refetch moves the
    // page head under the live draft.
    hoisted.page = {
      path: "AGENTS.md",
      content: "agent content",
      head_sha: "head-2",
    };
    rerender(<ContextWikiPagePane path="AGENTS.md" />);

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(hoisted.mutate).toHaveBeenCalledWith(
      expect.objectContaining({
        content: "my local edits",
        baseHead: "head-1",
      }),
      expect.anything(),
    );
  });
});

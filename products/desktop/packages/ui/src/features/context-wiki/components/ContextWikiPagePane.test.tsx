import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContextWikiPagePane } from "./ContextWikiPagePane";

const hoisted = vi.hoisted(() => ({
  page: {
    path: "AGENTS.md",
    content: "original content",
    head_sha: "head-1",
    updated_at: "2026-08-22T12:00:00Z",
  } as {
    path: string;
    content: string;
    head_sha: string;
    updated_at: string;
  } | null,
  saveError: null as Error | null,
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
    error: hoisted.saveError,
    isPending: false,
    reset: hoisted.reset,
  }),
}));

vi.mock("@posthog/ui/features/editor/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

// The real client pulls in @posthog/shared, which this package's vitest config
// does not resolve. The pane only needs these two classes for the instanceof
// checks on a failed save.
vi.mock("@posthog/api-client/posthog-client", () => ({
  ContextWikiConflictError: class ContextWikiConflictError extends Error {
    currentHead: string | null;
    constructor(currentHead: string | null) {
      super("The wiki changed since you started editing");
      this.currentHead = currentHead;
    }
  },
  ContextWikiLintError: class ContextWikiLintError extends Error {},
}));

const { ContextWikiConflictError } = await import(
  "@posthog/api-client/posthog-client"
);

describe("ContextWikiPagePane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.saveError = null;
    hoisted.page = {
      path: "AGENTS.md",
      content: "original content",
      head_sha: "head-1",
      updated_at: "2026-08-22T12:00:00Z",
    };
  });

  it("shows when the page was last updated", () => {
    render(<ContextWikiPagePane path="AGENTS.md" />);

    expect(screen.getByText("Updated")).toBeVisible();
  });

  it("saves against the head the draft was seeded from, not a head that moved under it mid-edit", async () => {
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
      updated_at: "2026-08-22T12:05:00Z",
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

  it("keeps the draft when a save conflicts, and retries it against the new head", async () => {
    const user = userEvent.setup();

    const { rerender } = render(<ContextWikiPagePane path="AGENTS.md" />);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(
      screen.getByPlaceholderText("Write markdown for this page…"),
      { target: { value: "my local edits" } },
    );

    // The save loses the race, and the refetch that follows brings in the
    // other writer's content.
    hoisted.saveError = new ContextWikiConflictError("head-9");
    hoisted.page = {
      path: "AGENTS.md",
      content: "their content",
      head_sha: "head-9",
      updated_at: "2026-08-22T12:10:00Z",
    };
    rerender(<ContextWikiPagePane path="AGENTS.md" />);

    // The draft the banner tells them about has to still be there.
    expect(
      screen.getByPlaceholderText("Write markdown for this page…"),
    ).toHaveValue("my local edits");

    await user.click(screen.getByRole("button", { name: "Save mine anyway" }));

    expect(hoisted.mutate).toHaveBeenLastCalledWith(
      expect.objectContaining({
        content: "my local edits",
        baseHead: "head-9",
      }),
      expect.anything(),
    );
  });
});

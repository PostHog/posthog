import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ContextWikiView } from "./ContextWikiView";

const hoisted = vi.hoisted(() => ({
  paths: ["AGENTS.md", "channels/growth.md"],
  mutate: vi.fn(),
  reset: vi.fn(),
  refetch: vi.fn(),
}));

vi.mock("../hooks/useContextWiki", () => ({
  useContextWikiTree: () => ({
    data: { head_sha: "head-1", paths: hoisted.paths },
    isLoading: false,
    error: null,
    refetch: hoisted.refetch,
  }),
  useContextWikiHealthReport: () => ({
    data: { head_sha: "head-1", findings: [] },
    isLoading: false,
    error: null,
    refetch: hoisted.refetch,
  }),
  useEnableContextWiki: () => ({
    mutate: vi.fn(),
    isPending: false,
    error: null,
  }),
  useContextWikiPage: (path: string) => ({
    data: { path, content: `saved ${path}`, head_sha: "head-1" },
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

// Stand in for the shared tree so the test drives selection through a stable
// button per page instead of the explorer's internal DOM.
vi.mock("@posthog/ui/primitives/FileExplorer", () => ({
  FileExplorer: ({
    onSelectPath,
    children,
  }: {
    onSelectPath: (path: string) => void;
    children: React.ReactNode;
  }) => (
    <div>
      {hoisted.paths.map((path) => (
        <button key={path} type="button" onClick={() => onSelectPath(path)}>
          {`select ${path}`}
        </button>
      ))}
      {children}
    </div>
  ),
}));

vi.mock("@posthog/ui/hooks/useSetHeaderContent", () => ({
  useSetHeaderContent: () => {},
}));

vi.mock("@posthog/ui/features/editor/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

vi.mock("@posthog/api-client/posthog-client", () => ({
  ContextWikiConflictError: class ContextWikiConflictError extends Error {},
  ContextWikiLintError: class ContextWikiLintError extends Error {},
  ContextWikiUnavailableError: class ContextWikiUnavailableError extends Error {},
}));

describe("ContextWikiView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("keeps an unsaved draft when another page is opened and this one comes back", async () => {
    const user = userEvent.setup();
    render(<ContextWikiView />);

    await user.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(
      screen.getByPlaceholderText("Write markdown for this page…"),
      { target: { value: "half-written thought" } },
    );

    // The explorer sits beside the editor, so clicking a sibling page mid-edit
    // is ordinary use — and used to discard the draft with the pane.
    await user.click(
      screen.getByRole("button", { name: "select channels/growth.md" }),
    );
    expect(screen.queryByDisplayValue("half-written thought")).toBeNull();

    await user.click(screen.getByRole("button", { name: "select AGENTS.md" }));

    expect(
      screen.getByPlaceholderText("Write markdown for this page…"),
    ).toHaveValue("half-written thought");
  });
});

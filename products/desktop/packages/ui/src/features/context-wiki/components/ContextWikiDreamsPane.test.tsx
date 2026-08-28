import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ContextWikiDreamsPane,
  firstSummaryLine,
} from "./ContextWikiDreamsPane";

const hoisted = vi.hoisted(() => ({
  dreams: [
    {
      sha: "b".repeat(40),
      date: "2026-08-18",
      committed_at: "2026-08-18T03:00:00Z",
      summary: "# Context dream — 2026-08-18\n\nSecond night summary.",
      pages_added: 1,
      pages_modified: 0,
      pages_deleted: 0,
    },
    {
      sha: "a".repeat(40),
      date: "2026-08-17",
      committed_at: "2026-08-17T03:00:00Z",
      summary: "# Context dream — 2026-08-17\n\nFirst night summary.",
      pages_added: 0,
      pages_modified: 2,
      pages_deleted: 0,
    },
  ],
  detail: {
    run: null as null | object,
    files: [
      {
        path: "areas/dreamt.md",
        status: "added",
        patch:
          "diff --git a/areas/dreamt.md b/areas/dreamt.md\nnew file mode 100644\nindex 0000000..1111111\n--- /dev/null\n+++ b/areas/dreamt.md\n@@ -0,0 +1 @@\n+# Dreamt\n",
        truncated: false,
      },
    ],
  },
  refetch: vi.fn(),
}));

vi.mock("../hooks/useContextWiki", () => ({
  useContextWikiDreams: () => ({
    data: { head_sha: "head-1", dreams: hoisted.dreams },
    isLoading: false,
    error: null,
    refetch: hoisted.refetch,
  }),
  useContextWikiDream: (sha: string) => ({
    data: {
      run: hoisted.dreams.find((dream) => dream.sha === sha) ?? null,
      files: hoisted.detail.files,
    },
    isLoading: false,
    error: null,
    refetch: hoisted.refetch,
  }),
}));

vi.mock("@posthog/ui/features/editor/components/MarkdownRenderer", () => ({
  MarkdownRenderer: ({ content }: { content: string }) => <div>{content}</div>,
}));

// The diff viewer needs browser APIs jsdom does not have; the pane only needs
// the patch-to-metadata conversion, which is the part worth keeping real.
vi.mock("@pierre/diffs/react", () => ({
  FileDiff: () => <div data-testid="file-diff" />,
}));

vi.mock("../../../shell/themeStore", () => ({
  useThemeStore: (selector: (s: { isDarkMode: boolean }) => unknown) =>
    selector({ isDarkMode: false }),
}));

describe("ContextWikiDreamsPane", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the newest run's summary and per-file changes, and switches runs", async () => {
    const user = userEvent.setup();
    render(<ContextWikiDreamsPane />);

    // Newest first, and the newest is selected without a click.
    expect(screen.getByText("Second night summary.")).toBeInTheDocument();
    expect(screen.getByText("areas/dreamt.md")).toBeInTheDocument();
    expect(screen.getByTestId("file-diff")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /2026-08-17/ }));

    // The detail pane follows the selection; the list keeps both previews.
    expect(screen.getByText("Dream run: 2026-08-17")).toBeInTheDocument();
    expect(screen.queryByText("Dream run: 2026-08-18")).toBeNull();
  });

  it.each([
    ["# Heading\n\nFirst prose line.\n\nSecond.", "First prose line."],
    ["# Only heading", ""],
    ["No heading at all.", "No heading at all."],
  ])("firstSummaryLine(%j) -> %j", (summary, expected) => {
    expect(firstSummaryLine(summary)).toBe(expected);
  });
});

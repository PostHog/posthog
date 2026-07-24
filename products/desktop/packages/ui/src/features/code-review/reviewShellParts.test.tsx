import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../code-editor/diffViewerStore", () => ({
  useDiffViewerStore: vi.fn(),
}));
vi.mock("../git-interaction/utils/diffStats", () => ({
  computeDiffStats: () => ({ linesAdded: 0, linesRemoved: 0 }),
}));
vi.mock("../../shell/themeStore", () => ({
  useThemeStore: vi.fn(() => ({ isDarkMode: false })),
}));
vi.mock("../../primitives/FileIcon", () => ({
  FileIcon: () => <span data-testid="file-icon" />,
}));

import {
  deriveCommentFileFilterState,
  filterReviewItemsByFilePaths,
  getCommentedFilePaths,
  type ReviewListItem,
} from "./commentFileFilter";
import {
  DeferredDiffPlaceholder,
  DiffFileHeader,
  findActiveScrollKey,
  findRenderedScrollAnchor,
} from "./reviewShellParts";

type FileDiffMetadata = import("@pierre/diffs/react").FileDiffMetadata;

function makeFileDiff(name: string): FileDiffMetadata {
  return {
    name,
    prevName: null,
    hunks: [{ additionLines: 3, deletionLines: 1 }],
  } as unknown as FileDiffMetadata;
}

function findSpan(
  container: HTMLElement,
  match: (s: HTMLSpanElement) => boolean,
): HTMLSpanElement {
  const spans = Array.from(container.querySelectorAll<HTMLSpanElement>("span"));
  const found = spans.find(match);
  if (!found) throw new Error("span not found");
  return found;
}

function renderHeader(path: string, commentCount?: number) {
  const diff = render(
    <DiffFileHeader
      fileDiff={makeFileDiff(path)}
      collapsed={false}
      onToggle={() => {}}
      commentCount={commentCount}
    />,
  );
  const deferred = render(
    <DeferredDiffPlaceholder
      filePath={path}
      linesAdded={10}
      linesRemoved={2}
      reason="line-limit"
      collapsed={false}
      onToggle={() => {}}
      commentCount={commentCount}
    />,
  );
  return { diff, deferred };
}

describe.each([
  ["DiffFileHeader", "diff" as const],
  ["DeferredDiffPlaceholder", "deferred" as const],
])("%s", (_name, which) => {
  it("renders the directory path and filename", () => {
    const rendered = renderHeader(
      "src/renderer/features/code-review/components/ReviewShell.tsx",
    )[which];

    const text = rendered.container.querySelector("button")?.textContent ?? "";
    expect(text).toContain("src/renderer/features/code-review/components/");
    expect(text).toContain("ReviewShell.tsx");
  });

  it("truncates the directory path and keeps the filename intact", () => {
    const rendered = renderHeader(
      "src/a/very/deeply/nested/structure/ReviewShell.tsx",
    )[which];

    // Inline styles were migrated to Tailwind utility classes; check classes
    // instead. The dir span gets the muted color + truncation utilities, the
    // file span gets bold weight + a non-shrinking flex behavior.
    const dirSpan = findSpan(rendered.container, (s) =>
      s.classList.contains("text-(--gray-9)"),
    );
    const fileSpan = findSpan(rendered.container, (s) =>
      s.classList.contains("font-semibold"),
    );

    expect(dirSpan.classList.contains("overflow-hidden")).toBe(true);
    expect(dirSpan.classList.contains("text-ellipsis")).toBe(true);
    expect(dirSpan.classList.contains("whitespace-nowrap")).toBe(true);

    expect(fileSpan.classList.contains("whitespace-nowrap")).toBe(true);
    expect(fileSpan.classList.contains("shrink-0")).toBe(true);

    expect(dirSpan.parentElement).toBe(fileSpan.parentElement);
    expect(dirSpan.parentElement?.classList.contains("flex")).toBe(true);
  });

  it("renders metadata before line changes", () => {
    const rendered = renderHeader("src/ReviewShell.tsx", 2)[which];
    const text = rendered.container.querySelector("button")?.textContent ?? "";
    const additions = which === "diff" ? "+3" : "+10";

    expect(text.indexOf("2 comments")).toBeLessThan(text.indexOf(additions));
  });
});

function setRect(element: HTMLElement, top: number, bottom: number) {
  element.getBoundingClientRect = vi.fn(() => ({ top, bottom }) as DOMRect);
}

describe("review scroll anchors", () => {
  it("finds a rendered anchor by its exact file key", () => {
    const root = document.createElement("div");
    const anchor = document.createElement("div");
    anchor.dataset.scrollKey = "src/[id]/file.ts";
    root.append(anchor);

    expect(findRenderedScrollAnchor(root, "src/[id]/file.ts")).toBe(anchor);
  });

  it("selects the last file starting at or above the scroll root top", () => {
    const root = document.createElement("div");
    const above = document.createElement("div");
    const active = document.createElement("div");
    const below = document.createElement("div");
    above.dataset.scrollKey = "above.ts";
    active.dataset.scrollKey = "active.ts";
    below.dataset.scrollKey = "below.ts";
    root.append(above, active, below);
    setRect(root, 100, 500);
    setRect(above, 20, 90);
    setRect(active, 80, 180);
    setRect(below, 180, 280);

    expect(findActiveScrollKey(root)).toBe("active.ts");
  });

  it("does not select a tall expanded file above the jump target", () => {
    const root = document.createElement("div");
    const expandedAbove = document.createElement("div");
    const target = document.createElement("div");
    const below = document.createElement("div");
    expandedAbove.dataset.scrollKey = "expanded-above.ts";
    target.dataset.scrollKey = "target.ts";
    below.dataset.scrollKey = "below.ts";
    root.append(expandedAbove, target, below);
    setRect(root, 100, 500);
    setRect(expandedAbove, -1000, 500);
    setRect(target, 100, 180);
    setRect(below, 180, 260);

    expect(findActiveScrollKey(root)).toBe("target.ts");
  });
});

describe("commented file filtering", () => {
  it("collects paths for all and unresolved comment threads", () => {
    const commentedPaths = getCommentedFilePaths(
      new Map([
        [
          1,
          {
            filePath: "src/commented.ts",
            isResolved: false,
            comments: [{ id: 1 }],
          },
        ],
        [
          2,
          {
            filePath: "src/resolved.ts",
            isResolved: true,
            comments: [{ id: 2 }],
          },
        ],
        [
          3,
          {
            filePath: "src/empty.ts",
            isResolved: false,
            comments: [],
          },
        ],
      ]) as Parameters<typeof getCommentedFilePaths>[0],
    );

    expect(commentedPaths).toEqual({
      all: new Set(["src/commented.ts", "src/resolved.ts"]),
      unresolved: new Set(["src/commented.ts"]),
    });
  });

  it("keeps matching files and their section headers", () => {
    const items: ReviewListItem[] = [
      { key: "section:staged", node: <span>Staged</span> },
      {
        key: "staged:a.ts",
        filePaths: ["a.ts"],
        node: <span>A</span>,
      },
      {
        key: "staged:b.ts",
        filePaths: ["b.ts"],
        node: <span>B</span>,
      },
      { key: "section:changes", node: <span>Changes</span> },
      {
        key: "unstaged:c.ts",
        filePaths: ["c.ts", "old-c.ts"],
        node: <span>C</span>,
      },
    ];

    expect(
      filterReviewItemsByFilePaths(items, new Set(["b.ts", "old-c.ts"])).map(
        (item) => item.key,
      ),
    ).toEqual([
      "section:staged",
      "staged:b.ts",
      "section:changes",
      "unstaged:c.ts",
    ]);
  });

  it("drops section headers without matching files", () => {
    const items: ReviewListItem[] = [
      { key: "section:staged", node: <span>Staged</span> },
      {
        key: "staged:a.ts",
        filePaths: ["a.ts"],
        node: <span>A</span>,
      },
      { key: "section:changes", node: <span>Changes</span> },
      {
        key: "unstaged:b.ts",
        filePaths: ["b.ts"],
        node: <span>B</span>,
      },
    ];

    expect(
      filterReviewItemsByFilePaths(items, new Set(["b.ts"])).map(
        (item) => item.key,
      ),
    ).toEqual(["section:changes", "unstaged:b.ts"]);
  });

  it("derives visible items and counts for the selected filter", () => {
    const items: ReviewListItem[] = [
      { key: "a.ts", filePaths: ["a.ts"], node: <span>A</span> },
      { key: "b.ts", filePaths: ["b.ts"], node: <span>B</span> },
      { key: "c.ts", filePaths: ["c.ts"], node: <span>C</span> },
    ];

    const state = deriveCommentFileFilterState({
      items,
      requestedFilter: "unresolved",
      commentedFilePaths: new Set(["a.ts", "b.ts"]),
      unresolvedCommentedFilePaths: new Set(["b.ts"]),
    });

    expect(state.activeFilter).toBe("unresolved");
    expect(state.visibleItems.map((item) => item.key)).toEqual(["b.ts"]);
    expect(state.commentedFileCount).toBe(2);
    expect(state.unresolvedCommentedFileCount).toBe(1);
  });

  it("keeps all files visible while comment paths are loading", () => {
    const items: ReviewListItem[] = [
      { key: "a.ts", filePaths: ["a.ts"], node: <span>A</span> },
    ];

    const state = deriveCommentFileFilterState({
      items,
      requestedFilter: "unresolved",
    });

    expect(state.activeFilter).toBe("none");
    expect(state.visibleItems).toBe(items);
  });
});

import type { PrCommentThread } from "@posthog/core/code-review/types";
import type { ReactNode } from "react";

export type CommentFileFilter = "none" | "commented" | "unresolved";

export interface ReviewListItem {
  key: string;
  scrollKey?: string;
  filePaths?: string[];
  node: ReactNode;
}

interface CommentFileFilterState {
  activeFilter: CommentFileFilter;
  visibleItems: ReviewListItem[];
  commentedFileCount: number;
  unresolvedCommentedFileCount: number;
}

interface DeriveCommentFileFilterStateArgs {
  items: ReviewListItem[];
  requestedFilter: CommentFileFilter;
  commentedFilePaths?: ReadonlySet<string>;
  unresolvedCommentedFilePaths?: ReadonlySet<string>;
}

export function getCommentedFilePaths(threads: Map<number, PrCommentThread>): {
  all: Set<string>;
  unresolved: Set<string>;
} {
  const all = new Set<string>();
  const unresolved = new Set<string>();

  for (const thread of threads.values()) {
    if (thread.comments.length === 0) continue;
    all.add(thread.filePath);
    if (!thread.isResolved) unresolved.add(thread.filePath);
  }

  return { all, unresolved };
}

export function filterReviewItemsByFilePaths(
  items: ReviewListItem[],
  filePaths: ReadonlySet<string>,
): ReviewListItem[] {
  const filteredItems: ReviewListItem[] = [];
  let pendingSectionItems: ReviewListItem[] = [];

  for (const item of items) {
    if (!item.filePaths) {
      pendingSectionItems = [item];
      continue;
    }

    if (!item.filePaths.some((filePath) => filePaths.has(filePath))) continue;

    filteredItems.push(...pendingSectionItems, item);
    pendingSectionItems = [];
  }

  return filteredItems;
}

export function deriveCommentFileFilterState({
  items,
  requestedFilter,
  commentedFilePaths,
  unresolvedCommentedFilePaths,
}: DeriveCommentFileFilterStateArgs): CommentFileFilterState {
  if (!commentedFilePaths || !unresolvedCommentedFilePaths) {
    return {
      activeFilter: "none",
      visibleItems: items,
      commentedFileCount: 0,
      unresolvedCommentedFileCount: 0,
    };
  }

  const commentedItems = filterReviewItemsByFilePaths(
    items,
    commentedFilePaths,
  );
  const unresolvedCommentedItems = filterReviewItemsByFilePaths(
    items,
    unresolvedCommentedFilePaths,
  );

  let visibleItems: ReviewListItem[];
  switch (requestedFilter) {
    case "commented":
      visibleItems = commentedItems;
      break;
    case "unresolved":
      visibleItems = unresolvedCommentedItems;
      break;
    case "none":
      visibleItems = items;
      break;
  }

  return {
    activeFilter: requestedFilter,
    visibleItems,
    commentedFileCount: commentedItems.filter((item) => item.filePaths).length,
    unresolvedCommentedFileCount: unresolvedCommentedItems.filter(
      (item) => item.filePaths,
    ).length,
  };
}

export function getEmptyReviewMessage(
  commentFilter: CommentFileFilter,
): string {
  switch (commentFilter) {
    case "commented":
      return "No files with comments";
    case "unresolved":
      return "No files with unresolved comments";
    case "none":
      return "No file changes to review";
  }
}

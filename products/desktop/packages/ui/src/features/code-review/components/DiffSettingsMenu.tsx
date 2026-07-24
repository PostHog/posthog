import { DotsThree } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@posthog/quill";
import { useDiffViewerStore } from "@posthog/ui/features/code-editor/diffViewerStore";
import type { CommentFileFilter } from "../commentFileFilter";
import { CommentFilterSubmenu } from "./CommentFilterSubmenu";

interface DiffSettingsMenuProps {
  commentedFileCount: number;
  unresolvedCommentedFileCount: number;
  commentFilter: CommentFileFilter;
  onCommentFilterChange?: (filter: CommentFileFilter) => void;
}

export function DiffSettingsMenu({
  commentedFileCount,
  unresolvedCommentedFileCount,
  commentFilter,
  onCommentFilterChange,
}: DiffSettingsMenuProps) {
  const wordWrap = useDiffViewerStore((s) => s.wordWrap);
  const toggleWordWrap = useDiffViewerStore((s) => s.toggleWordWrap);
  const wordDiffs = useDiffViewerStore((s) => s.wordDiffs);
  const toggleWordDiffs = useDiffViewerStore((s) => s.toggleWordDiffs);
  const hideWhitespaceChanges = useDiffViewerStore(
    (s) => s.hideWhitespaceChanges,
  );
  const toggleHideWhitespaceChanges = useDiffViewerStore(
    (s) => s.toggleHideWhitespaceChanges,
  );
  const showReviewComments = useDiffViewerStore((s) => s.showReviewComments);
  const toggleShowReviewComments = useDiffViewerStore(
    (s) => s.toggleShowReviewComments,
  );
  const handleToggleReviewComments = () => {
    if (showReviewComments && commentFilter !== "none") {
      onCommentFilterChange?.("none");
    }
    toggleShowReviewComments();
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            size="icon-sm"
            variant={commentFilter === "none" ? "default" : "primary"}
            aria-label={
              commentFilter === "none"
                ? "Diff settings"
                : `Diff settings, ${commentFilter} comment filter active`
            }
            className="rounded-xs"
          >
            <DotsThree size={16} weight="bold" />
          </Button>
        }
      />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={6}
        className="min-w-[180px]"
      >
        <DropdownMenuItem onClick={toggleWordWrap}>
          {wordWrap ? "Disable word wrap" : "Enable word wrap"}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={toggleWordDiffs}>
          {wordDiffs ? "Disable word diffs" : "Enable word diffs"}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={toggleHideWhitespaceChanges}>
          {hideWhitespaceChanges ? "Show whitespace" : "Hide whitespace"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={handleToggleReviewComments}>
          {showReviewComments ? "Hide review comments" : "Show review comments"}
        </DropdownMenuItem>
        {showReviewComments && onCommentFilterChange && (
          <CommentFilterSubmenu
            commentedFileCount={commentedFileCount}
            unresolvedCommentedFileCount={unresolvedCommentedFileCount}
            commentFilter={commentFilter}
            onCommentFilterChange={onCommentFilterChange}
          />
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

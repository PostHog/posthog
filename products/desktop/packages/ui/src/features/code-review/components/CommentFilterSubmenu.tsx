import {
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@posthog/quill";
import type { CommentFileFilter } from "../commentFileFilter";

interface CommentFilterSubmenuProps {
  commentedFileCount: number;
  unresolvedCommentedFileCount: number;
  commentFilter: CommentFileFilter;
  onCommentFilterChange: (filter: CommentFileFilter) => void;
}

function getCommentFilterSuffix(commentFilter: CommentFileFilter): string {
  switch (commentFilter) {
    case "commented":
      return " · All";
    case "unresolved":
      return " · Unresolved";
    case "none":
      return "";
  }
}

export function CommentFilterSubmenu({
  commentedFileCount,
  unresolvedCommentedFileCount,
  commentFilter,
  onCommentFilterChange,
}: CommentFilterSubmenuProps) {
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        Comment filter{getCommentFilterSuffix(commentFilter)}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent side="right" sideOffset={4}>
        <DropdownMenuRadioGroup
          value={commentFilter === "none" ? "" : commentFilter}
          onValueChange={(value) =>
            onCommentFilterChange(value as CommentFileFilter)
          }
        >
          <DropdownMenuRadioItem value="commented">
            All comments ({commentedFileCount})
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="unresolved">
            Unresolved comments ({unresolvedCommentedFileCount})
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        {commentFilter !== "none" && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => onCommentFilterChange("none")}>
              Clear comment filter
            </DropdownMenuItem>
          </>
        )}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

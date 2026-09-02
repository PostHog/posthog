import type { AnnotationSide, FileDiffOptions } from "@pierre/diffs";
import type { PrReviewComment } from "@posthog/shared";

export type DiffSource = "local" | "branch" | "pr";

export type ResolvedDiffSource = DiffSource;

export interface DraftComment {
  id: string;
  taskId: string;
  filePath: string;
  startLine: number;
  endLine: number;
  side: AnnotationSide;
  text: string;
  createdAt: number;
}

export interface PrCommentThread {
  rootId: number;
  nodeId: string;
  isResolved: boolean;
  comments: PrReviewComment[];
  filePath: string;
}

export interface HunkRevertMetadata {
  kind: "hunk-revert";
  hunkIndex: number;
}

export interface CommentMetadata {
  kind: "comment";
  startLine: number;
  endLine: number;
  side: AnnotationSide;
}

export interface DraftCommentMetadata {
  kind: "draft-comment";
  draftId: string;
  startLine: number;
  endLine: number;
  side: AnnotationSide;
}

export interface PrCommentMetadata {
  kind: "pr-comment";
  threadId: number;
  nodeId: string;
  isResolved: boolean;
  comments: PrReviewComment[];
  isOutdated: boolean;
  isFileLevel: boolean;
  startLine: number | null;
  endLine: number;
  side: AnnotationSide;
}

export type AnnotationMetadata =
  | HunkRevertMetadata
  | CommentMetadata
  | DraftCommentMetadata
  | PrCommentMetadata;

export type DiffOptions = FileDiffOptions<AnnotationMetadata>;

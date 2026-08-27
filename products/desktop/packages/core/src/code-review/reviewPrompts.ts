import type { AnnotationSide } from "@pierre/diffs";
import type { PrReviewComment } from "@posthog/shared";
import type { DraftComment } from "./types";

function escapeXmlAttr(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function formatThreadForPrompt(comments: PrReviewComment[]): string {
  return comments.map((c) => `@${c.user.login}:\n> ${c.body}`).join("\n\n");
}

function formatPrCommentPromptContext(
  filePath: string,
  line: number,
  side: "old" | "new",
  comments: PrReviewComment[],
): string {
  const escapedPath = escapeXmlAttr(filePath);
  const thread = formatThreadForPrompt(comments);
  return `<file path="${escapedPath}" />, line ${line} (${side}):\n\n${thread}`;
}

function formatLineRef(startLine: number, endLine: number): string {
  return startLine === endLine
    ? `line ${startLine}`
    : `lines ${startLine}-${endLine}`;
}

function formatSideLabel(side: AnnotationSide): "old" | "new" {
  return side === "deletions" ? "old" : "new";
}

export function buildInlineCommentPrompt(
  filePath: string,
  startLine: number,
  endLine: number,
  side: AnnotationSide,
  comment: string,
): string {
  const lineRef = formatLineRef(startLine, endLine);
  const sideLabel = formatSideLabel(side);
  const escapedPath = escapeXmlAttr(filePath);
  return `In file <file path="${escapedPath}" />, ${lineRef} (${sideLabel}):\n\n${comment}`;
}

/** File + line-range reference with no diff side label (not a review comment). */
export function buildFileLineReferencePrompt(
  filePath: string,
  startLine: number,
  endLine: number,
  comment: string,
): string {
  const lineRef = formatLineRef(startLine, endLine);
  const escapedPath = escapeXmlAttr(filePath);
  return `In file <file path="${escapedPath}" />, ${lineRef}:\n\n${comment}`;
}

export function buildBatchedInlineCommentsPrompt(
  drafts: DraftComment[],
): string {
  if (drafts.length === 0) return "";
  if (drafts.length === 1) {
    const [d] = drafts;
    return buildInlineCommentPrompt(
      d.filePath,
      d.startLine,
      d.endLine,
      d.side,
      d.text,
    );
  }
  const items = drafts
    .map((d) => {
      const lineRef = formatLineRef(d.startLine, d.endLine);
      const sideLabel = formatSideLabel(d.side);
      const escapedPath = escapeXmlAttr(d.filePath);
      const indented = d.text
        .split("\n")
        .map((line) => `  ${line}`)
        .join("\n");
      return `- In file <file path="${escapedPath}" />, ${lineRef} (${sideLabel}):\n${indented}`;
    })
    .join("\n\n");
  return `Please address these review comments:\n\n${items}`;
}

export function buildFixPrCommentPrompt(
  filePath: string,
  line: number,
  side: "old" | "new",
  comments: PrReviewComment[],
): string {
  const context = formatPrCommentPromptContext(filePath, line, side, comments);
  return `Fix this PR review comment on ${context}`;
}

export function buildAskAboutPrCommentPrompt(
  filePath: string,
  line: number,
  side: "old" | "new",
  comments: PrReviewComment[],
): string {
  const context = formatPrCommentPromptContext(filePath, line, side, comments);
  return `Help me understand this PR review comment on ${context}\n\nWhat is this comment asking for and how should I address it? Do not make any changes, your job is simply to chat with me about this comment. If I need further changes, I'll ask.`;
}

export function buildChatAboutPrCommentPrompt(
  filePath: string,
  line: number,
  side: "old" | "new",
  comments: PrReviewComment[],
  message: string,
): string {
  const context = formatPrCommentPromptContext(filePath, line, side, comments);
  return `Regarding this PR review comment on ${context}\n\n${message}`;
}

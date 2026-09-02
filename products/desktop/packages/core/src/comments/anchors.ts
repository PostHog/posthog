import type { CommentScope } from "@posthog/api-client/posthog-client";
import { z } from "zod";

const CONTEXT_LENGTH = 32;
const MAX_QUOTE_LENGTH = 10_000;

/**
 * Addresses one commentable thing. `itemId` must be the resource's STABLE id
 * (an artifact id, a canvas row id) — never a name or a version, so comments
 * survive renames and reverts.
 */
export type CommentTarget = {
  scope: CommentScope;
  itemId: string;
};

/** The target as one string, for map keys and cache-key membership tests. */
export function commentTargetKey(target: CommentTarget): string {
  return `${target.scope}:${target.itemId}`;
}

export function isSameCommentTarget(
  a: CommentTarget | null,
  b: CommentTarget | null,
): boolean {
  return a?.scope === b?.scope && a?.itemId === b?.itemId;
}

export const textCommentAnchorDataSchema = z.object({
  quote: z.string().min(1).max(MAX_QUOTE_LENGTH),
  prefix: z.string().max(CONTEXT_LENGTH),
  suffix: z.string().max(CONTEXT_LENGTH),
  start: z.number().int().nonnegative(),
  end: z.number().int().positive(),
});

export const textCommentAnchorSchema = textCommentAnchorDataSchema
  .extend({
    kind: z.literal("text"),
  })
  .refine(({ start, end }) => end > start, {
    message: "Text anchor end must follow its start",
  });

export const regionCommentAnchorSchema = z.object({
  kind: z.literal("region"),
  x: z.number().min(0).max(1),
  y: z.number().min(0).max(1),
  width: z.number().min(0).max(1),
  height: z.number().min(0).max(1),
});

const documentCommentAnchorSchema = z.object({
  kind: z.literal("document"),
});

export const commentAnchorSchema = z.discriminatedUnion("kind", [
  textCommentAnchorSchema,
  regionCommentAnchorSchema,
  documentCommentAnchorSchema,
]);

export type TextCommentAnchor = z.infer<typeof textCommentAnchorSchema>;
export type RegionCommentAnchor = z.infer<typeof regionCommentAnchorSchema>;
export type CommentAnchor = z.infer<typeof commentAnchorSchema>;

export const commentContextSchema = z.object({
  anchor: commentAnchorSchema,
  threadState: z.enum(["resolved", "open"]).optional(),
  /** Immutable canvas source version rendered when the comment was made. */
  canvasVersionId: z.string().min(1).optional(),
  // The task the commented resource belongs to. Artifact and canvas ids live in a run's
  // JSON rather than a table, so the server can't get back to the task without being told.
  taskId: z.string().optional(),
});

export type CommentContext = z.infer<typeof commentContextSchema>;

export function parseCommentContext(value: unknown): CommentContext | null {
  const parsed = commentContextSchema.safeParse(value);
  return parsed.success ? parsed.data : null;
}

export type ThreadStateComment = {
  created_at: string;
  item_context?: unknown;
};

export function isThreadResolved(
  root: { completed_at?: string | null },
  replies: ThreadStateComment[],
): boolean {
  const latestState = replies
    .map((comment) => ({
      createdAt: comment.created_at,
      state: parseCommentContext(comment.item_context)?.threadState,
    }))
    .filter(
      (
        entry,
      ): entry is {
        createdAt: string;
        state: "resolved" | "open";
      } => !!entry.state,
    )
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt))
    .at(-1)?.state;
  return latestState ? latestState === "resolved" : !!root.completed_at;
}

export type ResolvedTextAnchor = {
  start: number;
  end: number;
  status: "exact" | "reanchored";
};

export function createTextCommentAnchor(
  text: string,
  start: number,
  end: number,
): TextCommentAnchor | null {
  const safeStart = Math.max(0, Math.min(start, text.length));
  const safeEnd = Math.max(safeStart, Math.min(end, text.length));
  const quote = text.slice(safeStart, safeEnd);
  if (!quote.trim() || quote.length > MAX_QUOTE_LENGTH) return null;

  return {
    kind: "text",
    quote,
    prefix: text.slice(Math.max(0, safeStart - CONTEXT_LENGTH), safeStart),
    suffix: text.slice(safeEnd, safeEnd + CONTEXT_LENGTH),
    start: safeStart,
    end: safeEnd,
  };
}

/**
 * Resolve a persisted text quote without ever guessing. The stored position is
 * verified first. If content moved, prefix/suffix disambiguate quote matches;
 * ties are deliberately treated as orphaned.
 */
export function resolveTextCommentAnchor(
  text: string,
  anchor: TextCommentAnchor,
): ResolvedTextAnchor | null {
  if (text.slice(anchor.start, anchor.end) === anchor.quote) {
    return { start: anchor.start, end: anchor.end, status: "exact" };
  }

  const candidates: number[] = [];
  let from = 0;
  while (from <= text.length - anchor.quote.length) {
    const match = text.indexOf(anchor.quote, from);
    if (match < 0) break;
    candidates.push(match);
    from = match + Math.max(anchor.quote.length, 1);
  }
  if (candidates.length === 0) return null;
  if (candidates.length === 1) {
    const start = candidates[0];
    return {
      start,
      end: start + anchor.quote.length,
      status: "reanchored",
    };
  }

  const ranked = candidates
    .map((start) => {
      const end = start + anchor.quote.length;
      const prefix = text.slice(
        Math.max(0, start - anchor.prefix.length),
        start,
      );
      const suffix = text.slice(end, end + anchor.suffix.length);
      let score = 0;
      if (anchor.prefix && prefix === anchor.prefix) score += 2;
      if (anchor.suffix && suffix === anchor.suffix) score += 2;
      return { start, score };
    })
    .sort((a, b) => b.score - a.score);
  if (ranked[0].score === 0 || ranked[0].score === ranked[1].score) return null;

  return {
    start: ranked[0].start,
    end: ranked[0].start + anchor.quote.length,
    status: "reanchored",
  };
}

import {
  type FeedQueryIssue,
  type FeedQueryPlanContext,
  type FeedQueryToken,
  type Group,
  groupOf,
  MATCH_ALL,
  memberResolver,
  normalize,
  type ParsedFeedQuery,
  spaceResolver,
} from "./feedQuery";

/** The canvas fields the canvas search predicate reads. */
export interface FeedQueryCanvas {
  name: string;
  description?: string;
  channelId: string;
  createdByUuid?: string;
  pinnedAt?: number;
}

export interface CanvasQueryPlan {
  matches: (canvas: FeedQueryCanvas) => boolean;
  issues: FeedQueryIssue[];
}

/**
 * The canvas-only plan behind `type:canvas` in the command palette. Canvases
 * load as one list, so every filter is a client-side predicate. `created-by:`,
 * `space:`, `is:pinned` and free text apply. Every other token is task-shaped
 * and is reported as unsupported rather than half-applied.
 */
export function planCanvasQuery(
  parsed: ParsedFeedQuery,
  context: FeedQueryPlanContext,
): CanvasQueryPlan {
  const issues: FeedQueryIssue[] = [...parsed.issues];
  const resolveMembers = memberResolver(context, issues);
  const resolveSpace = spaceResolver(context, issues);
  const predicates: ((canvas: FeedQueryCanvas) => boolean)[] = [];

  const groups = new Map<string, Group>();
  for (const token of parsed.tokens) {
    const key =
      token.key === "is" && normalize(token.value) === "pinned"
        ? "pinned"
        : token.key;
    const group = groupOf(groups, key);
    (token.negated ? group.negatives : group.positives).push(token);
  }

  // Positive values OR together and negated values exclude. A positive filter
  // that resolves to nothing matches nothing, not every canvas, the same as an
  // unknown teammate or space in task mode.
  const addIdFilter = (
    group: Group,
    resolve: (token: FeedQueryToken) => string[],
    idOf: (canvas: FeedQueryCanvas) => string | undefined,
  ) => {
    if (group.positives.length > 0) {
      const wanted = new Set(group.positives.flatMap(resolve));
      predicates.push((canvas) => {
        const id = idOf(canvas);
        return id !== undefined && wanted.has(id);
      });
    }
    const excluded = new Set(group.negatives.flatMap(resolve));
    if (excluded.size > 0) {
      predicates.push((canvas) => {
        const id = idOf(canvas);
        return id === undefined || !excluded.has(id);
      });
    }
  };

  for (const [key, group] of groups) {
    if (key === "created-by") {
      addIdFilter(
        group,
        (token) => resolveMembers(token).map((member) => member.uuid),
        (canvas) => canvas.createdByUuid,
      );
    } else if (key === "space") {
      addIdFilter(
        group,
        (token) => {
          const space = resolveSpace(token);
          return space ? [space.id] : [];
        },
        (canvas) => canvas.channelId,
      );
    } else if (key === "pinned") {
      if (group.positives.length > 0) {
        predicates.push((canvas) => canvas.pinnedAt != null);
      }
      if (group.negatives.length > 0) {
        predicates.push((canvas) => canvas.pinnedAt == null);
      }
    } else {
      for (const token of [...group.positives, ...group.negatives]) {
        const isScope =
          key === "type" &&
          !token.negated &&
          normalize(token.value) === "canvas";
        if (isScope) continue;
        issues.push({
          raw: token.raw,
          kind: "unsupported",
          message: `Canvas search doesn't support "${token.raw}", so it is ignored`,
        });
      }
    }
  }

  const text = normalize(parsed.text);
  if (text) {
    predicates.push(
      (canvas) =>
        canvas.name.toLowerCase().includes(text) ||
        (canvas.description ?? "").toLowerCase().includes(text),
    );
  }

  return {
    matches:
      predicates.length === 0
        ? MATCH_ALL
        : (canvas) => predicates.every((p) => p(canvas)),
    issues,
  };
}

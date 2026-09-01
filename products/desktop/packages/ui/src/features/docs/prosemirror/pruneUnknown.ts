import type { Schema } from "@tiptap/pm/model";

type Json = Record<string, unknown>;

function isJson(value: unknown): value is Json {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Drops nodes and marks the editor no longer knows about.
 *
 * A stored page outlives the build that wrote it. ProseMirror refuses a document
 * that names a node type its schema does not have, and refusing means an empty
 * page in front of the person who wrote it. So an unknown node is dropped and
 * the rest of the page survives.
 *
 * Unknown blocks keep their children where the children are known, so a page
 * that gains a wrapper in one release does not lose its text in the next.
 */
export function pruneUnknown<T>(content: T, schema: Schema): T {
  if (!isJson(content)) return content;
  const pruned = pruneNode(content, schema, true);
  return (pruned[0] ?? content) as T;
}

function pruneNode(node: Json, schema: Schema, isRoot: boolean): Json[] {
  const type = typeof node.type === "string" ? node.type : null;
  const children = Array.isArray(node.content) ? node.content : null;
  const prunedChildren = children
    ? children
        .filter(isJson)
        .flatMap((child) => pruneNode(child, schema, false))
    : null;

  if (!isRoot && (!type || !schema.nodes[type])) {
    // The node is gone; its children are not to blame.
    return prunedChildren ?? [];
  }

  const next: Json = { ...node };
  if (prunedChildren) next.content = prunedChildren;
  if (Array.isArray(node.marks)) {
    next.marks = node.marks
      .filter(isJson)
      .filter(
        (mark) => typeof mark.type === "string" && !!schema.marks[mark.type],
      );
  }
  return [next];
}

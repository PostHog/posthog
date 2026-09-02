import type { ScoutScratchpadEntry } from "@posthog/api-client/posthog-client";

/**
 * Read-only view helpers over the scout fleet's durable memory
 * (`SignalScratchpad` on the Cloud backend). The harness writes these notes on
 * internal scope while scanning a project; humans only inspect them. These pure
 * functions mirror the Cloud `scratchpadLogic` selectors so the desktop surface
 * groups, labels, and searches the fleet's memory the same way.
 */

/** The list shows two ways to read the memory: newest-first (the API's native
 * order) or clustered by the key namespace scouts choose (`tags:*`, `dedupe:*`). */
export type ScratchpadGrouping = "recent" | "topic";

/** One namespace cluster in the "By topic" view: the raw prefix, a friendly
 * label, and the entries that share it. */
export interface ScratchpadNamespaceGroup {
  namespace: string;
  label: string;
  entries: ScoutScratchpadEntry[];
}

/** Scouts namespace keys with a leading `prefix:` (e.g. `tags:errors:taxonomy`).
 * Everything before the first colon is the topic; keys without one fall into a
 * shared "general" bucket. */
export function scratchpadNamespaceOf(key: string): string {
  const idx = key.indexOf(":");
  return idx > 0 ? key.slice(0, idx) : "general";
}

export function humanizeNamespace(namespace: string): string {
  if (namespace === "general") {
    return "General";
  }
  return namespace
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/** Split a key into its `kind` prefix (what the scout was doing when it wrote
 * the note) and the human-readable body after the first colon. */
export function splitScratchpadKey(key: string): {
  kind: string | null;
  body: string;
} {
  const idx = key.indexOf(":");
  return idx > 0
    ? { kind: key.slice(0, idx), body: key.slice(idx + 1) }
    : { kind: null, body: key };
}

/** `signals-scout-apm` → `apm`. The fleet prefix is noise once you're inside
 * the scouts surface. */
export function scoutDisplayName(skill: string): string {
  return skill.replace(/^signals-scout-/, "");
}

/**
 * Group entries by their key namespace. Entries arrive newest-first; that order
 * is preserved within each cluster, and the clusters are ordered by their most
 * recently touched entry so the liveliest topic floats to the top.
 */
export function groupScratchpadEntries(
  entries: ScoutScratchpadEntry[],
): ScratchpadNamespaceGroup[] {
  const byNamespace = new Map<string, ScoutScratchpadEntry[]>();
  for (const entry of entries) {
    const namespace = scratchpadNamespaceOf(entry.key);
    const bucket = byNamespace.get(namespace);
    if (bucket) {
      bucket.push(entry);
    } else {
      byNamespace.set(namespace, [entry]);
    }
  }
  return [...byNamespace.entries()]
    .map(([namespace, namespaceEntries]) => ({
      namespace,
      label: humanizeNamespace(namespace),
      entries: namespaceEntries,
    }))
    .sort((a, b) =>
      (b.entries[0]?.updated_at ?? "").localeCompare(
        a.entries[0]?.updated_at ?? "",
      ),
    );
}

/**
 * Case-insensitive client-side search over key + content. The Cloud endpoint
 * exposes a server-side `?text=` ILIKE, but the desktop surface pulls the whole
 * newest-first window once and filters here so typing is instant and doesn't
 * fire a request per keystroke.
 */
export function filterScratchpadEntries(
  entries: ScoutScratchpadEntry[],
  search: string,
): ScoutScratchpadEntry[] {
  const query = search.trim().toLowerCase();
  if (!query) {
    return entries;
  }
  return entries.filter(
    (entry) =>
      entry.key.toLowerCase().includes(query) ||
      entry.content.toLowerCase().includes(query),
  );
}
